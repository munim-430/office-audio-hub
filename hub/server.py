"""
Manager Hub FastAPI Application & Web Server
Provides secure REST APIs, WebSocket streaming endpoints, and the Web Dashboard.
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    HTTPException,
    status,
    Request,
    Response
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from common.config import (
    DEFAULT_HUB_PORT,
    DEFAULT_HUB_HOST,
    DEFAULT_STORAGE_DIR,
    DEFAULT_AUDIO_DIR,
    DEFAULT_DB_FILE
)
from common.crypto import hash_password, verify_password, generate_session_token
from hub.pairing import DeviceRegistry
from hub.storage import ChunkStorageEngine
from hub.stream_manager import StreamManager

logger = logging.getLogger("HubServer")

# Pydantic Schemas
class SetupPasswordRequest(BaseModel):
    password: str

class LoginRequest(BaseModel):
    password: str

class PairingRequest(BaseModel):
    pairing_code: str
    device_id: str
    name: str
    hostname: Optional[str] = ""

def create_app(
    db_path: Path = DEFAULT_DB_FILE,
    audio_dir: Path = DEFAULT_AUDIO_DIR,
    static_dir: Optional[Path] = None
) -> FastAPI:
    """Application factory for Manager Hub."""
    app = FastAPI(title="Office Audio Hub", version="1.0.0")

    device_registry = DeviceRegistry(db_path=db_path)
    storage_engine = ChunkStorageEngine(base_dir=audio_dir, db_path=db_path)
    stream_manager = StreamManager(storage_engine=storage_engine, device_registry=device_registry)

    # In-memory session store (session_token -> expiration_timestamp)
    active_sessions: Dict[str, float] = {}
    SESSION_DURATION_HOURS = 24

    if static_dir is None:
        static_dir = Path(__file__).parent / "static"

    # Dependency for Admin Authentication
    async def get_current_admin(request: Request) -> bool:
        salt = device_registry.get_setting("admin_password_salt")
        if not salt:
            # First run: no password set yet
            return True
            
        token = request.cookies.get("hub_session") or request.headers.get("X-Hub-Session")
        if not token or token not in active_sessions:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
            
        if time.time() > active_sessions[token]:
            del active_sessions[token]
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
            
        return True

    # --- REST Endpoints ---

    @app.get("/api/auth/status")
    async def get_auth_status(request: Request):
        salt = device_registry.get_setting("admin_password_salt")
        has_password = bool(salt)
        token = request.cookies.get("hub_session") or request.headers.get("X-Hub-Session")
        is_authenticated = bool(token and token in active_sessions and time.time() <= active_sessions[token])
        return {
            "has_password": has_password,
            "is_authenticated": is_authenticated or not has_password
        }

    @app.post("/api/auth/setup")
    async def setup_admin_password(body: SetupPasswordRequest):
        existing_salt = device_registry.get_setting("admin_password_salt")
        if existing_salt:
            raise HTTPException(status_code=400, detail="Password already configured. Use login instead.")
        if len(body.password.strip()) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
            
        salt_hex, hash_hex = hash_password(body.password.strip())
        device_registry.set_setting("admin_password_salt", salt_hex)
        device_registry.set_setting("admin_password_hash", hash_hex)
        
        session_token = generate_session_token()
        active_sessions[session_token] = time.time() + (SESSION_DURATION_HOURS * 3600)
        
        response = JSONResponse({"status": "success", "message": "Admin password established"})
        response.set_cookie("hub_session", session_token, httponly=True, max_age=SESSION_DURATION_HOURS * 3600)
        return response

    @app.post("/api/auth/login")
    async def admin_login(body: LoginRequest):
        salt_hex = device_registry.get_setting("admin_password_salt")
        hash_hex = device_registry.get_setting("admin_password_hash")
        if not salt_hex or not hash_hex:
            # No password set
            session_token = generate_session_token()
            active_sessions[session_token] = time.time() + (SESSION_DURATION_HOURS * 3600)
            return {"status": "success", "session_token": session_token}

        if not verify_password(body.password, salt_hex, hash_hex):
            raise HTTPException(status_code=401, detail="Invalid admin password")

        session_token = generate_session_token()
        active_sessions[session_token] = time.time() + (SESSION_DURATION_HOURS * 3600)
        
        response = JSONResponse({"status": "success", "session_token": session_token})
        response.set_cookie("hub_session", session_token, httponly=True, max_age=SESSION_DURATION_HOURS * 3600)
        return response

    @app.post("/api/auth/logout")
    async def admin_logout(request: Request):
        token = request.cookies.get("hub_session")
        if token and token in active_sessions:
            del active_sessions[token]
        response = JSONResponse({"status": "logged_out"})
        response.delete_cookie("hub_session")
        return response

    @app.post("/api/pair")
    async def pair_employee_agent(req: PairingRequest):
        """Used by Employee Agent on first launch to pair using the 6-digit code."""
        auth_token = device_registry.pair_device(
            pairing_code=req.pairing_code,
            device_id=req.device_id,
            name=req.name,
            hostname=req.hostname or ""
        )
        if not auth_token:
            raise HTTPException(status_code=400, detail="Invalid or expired pairing code")
        return {
            "status": "paired",
            "device_id": req.device_id,
            "auth_token": auth_token
        }

    @app.get("/api/pairing/code", dependencies=[Depends(get_current_admin)])
    async def get_pairing_code():
        code = device_registry.get_or_create_pairing_code()
        ttl = max(0, int(device_registry.pairing_code_expires_at - time.time()))
        return {"pairing_code": code, "expires_in_seconds": ttl}

    @app.post("/api/pairing/code/regenerate", dependencies=[Depends(get_current_admin)])
    async def regenerate_pairing_code():
        device_registry.active_pairing_code = None
        code = device_registry.get_or_create_pairing_code()
        ttl = max(0, int(device_registry.pairing_code_expires_at - time.time()))
        return {"pairing_code": code, "expires_in_seconds": ttl}

    @app.get("/api/devices", dependencies=[Depends(get_current_admin)])
    async def list_devices():
        return stream_manager.get_devices_status()

    @app.get("/api/chunks", dependencies=[Depends(get_current_admin)])
    async def get_recorded_chunks(device_id: Optional[str] = None, date: Optional[str] = None):
        chunks = storage_engine.query_chunks(device_id=device_id, date_str=date)
        return chunks

    @app.get("/api/chunks/{chunk_id}/wav")
    async def download_chunk_wav(chunk_id: str, request: Request):
        # Allow streaming WAV to browser
        wav_bytes = storage_engine.export_chunk_to_wav_bytes(chunk_id)
        if not wav_bytes:
            raise HTTPException(status_code=404, detail="Chunk not found or empty")
            
        import io
        return StreamingResponse(
            io.BytesIO(wav_bytes),
            media_type="audio/wav",
            headers={"Content-Disposition": f'inline; filename="{chunk_id}.wav"'}
        )

    # --- WebSockets ---

    @app.websocket("/ws/agent")
    async def agent_audio_websocket(websocket: WebSocket):
        """Continuous binary WebSocket endpoint for Employee Agents."""
        await websocket.accept()
        
        # Initial auth handshake packet or headers
        device_id = None
        try:
            init_msg = await websocket.receive()
            if "bytes" in init_msg and init_msg["bytes"]:
                raw_bytes = init_msg["bytes"]
                from common.protocol import decode_audio_packet, PacketType
                packet = decode_audio_packet(raw_bytes)
                if packet.packet_type == PacketType.AUTH_REQUEST:
                    auth_data = json.loads(packet.payload.decode('utf-8'))
                    dev_id = auth_data.get("device_id")
                    token = auth_data.get("auth_token")
                    if not device_registry.verify_device_token(dev_id, token):
                        await websocket.close(code=4001, reason="Unauthorized device token")
                        return
                    device_id = dev_id
                    stream_manager.register_agent(device_id, websocket)
                    # Respond with AUTH_RESPONSE
                    from common.protocol import encode_audio_packet
                    resp = encode_audio_packet(
                        packet_type=PacketType.AUTH_RESPONSE,
                        device_id=device_id,
                        timestamp_ms=int(time.time() * 1000),
                        sequence_num=0,
                        payload=json.dumps({"status": "authenticated"}).encode('utf-8')
                    )
                    await websocket.send_bytes(resp)
                else:
                    await websocket.close(code=4002, reason="First packet must be AUTH_REQUEST")
                    return
            else:
                await websocket.close(code=4002, reason="Binary auth packet expected")
                return

            # Continuous streaming loop
            while True:
                msg = await websocket.receive()
                if "bytes" in msg and msg["bytes"]:
                    await stream_manager.handle_agent_packet(msg["bytes"])

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("Agent websocket error (%s): %s", device_id, e)
        finally:
            if device_id:
                stream_manager.unregister_agent(device_id)

    @app.websocket("/ws/dashboard")
    async def dashboard_websocket(websocket: WebSocket):
        """Dashboard WebSocket for real-time telemetry and sub-second live audio listening."""
        await websocket.accept()
        subscribed_device: Optional[str] = None
        try:
            while True:
                msg_text = await websocket.receive_text()
                data = json.loads(msg_text)
                action = data.get("action")
                
                if action == "subscribe_live":
                    target_device = data.get("device_id")
                    if subscribed_device:
                        stream_manager.unsubscribe_dashboard(websocket, subscribed_device)
                    subscribed_device = target_device
                    stream_manager.subscribe_dashboard(websocket, target_device)
                    await websocket.send_text(json.dumps({
                        "type": "subscribed",
                        "device_id": target_device
                    }))
                    
                elif action == "unsubscribe_live":
                    if subscribed_device:
                        stream_manager.unsubscribe_dashboard(websocket, subscribed_device)
                        subscribed_device = None
                    await websocket.send_text(json.dumps({"type": "unsubscribed"}))
                    
                elif action == "get_telemetry":
                    devices = stream_manager.get_devices_status()
                    await websocket.send_text(json.dumps({
                        "type": "telemetry",
                        "devices": devices
                    }))

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("Dashboard websocket error: %s", e)
        finally:
            stream_manager.unsubscribe_dashboard(websocket)

    # Static assets mount
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def serve_index():
            index_path = static_dir / "index.html"
            if index_path.exists():
                return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>Office Audio Hub</h1><p>Dashboard files missing.</p>")

    return app
