#!/usr/bin/env python3
"""
Manager Hub Entry Point (ManagerHub.exe)
Launches the local-first office audio server and opens the browser console.
"""

import sys
import os
import socket
import argparse
import webbrowser
import logging
from pathlib import Path
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ManagerHub")

def get_local_ip() -> str:
    """Discovers the local LAN IP address for employee laptop pairing."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def print_banner(host: str, port: int, local_ip: str):
    print("\n" + "="*65)
    print("      🎙️  KEYSTONE OVERSEAS — OFFICE AUDIO HUB (MANAGER)     ")
    print("="*65)
    print(f"  Local Dashboard URL:    http://localhost:{port}")
    if local_ip != "127.0.0.1":
        print(f"  Office LAN Address:     http://{local_ip}:{port}")
    print(f"  Employee Connect URL:   http://{local_ip}:{port}")
    print("  Storage Location:       storage/audio/ (100% Local Disk)")
    print("="*65)
    print("  Press Ctrl+C to stop the Manager Hub gracefully.\n")

def main():
    parser = argparse.ArgumentParser(description="Office Audio Hub - Manager Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open web browser automatically")
    parser.add_argument("--data-dir", default="storage", help="Data directory path")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "hub.db"
    audio_dir = data_dir / "audio"

    from hub.server import create_app
    app = create_app(db_path=db_path, audio_dir=audio_dir)

    local_ip = get_local_ip()
    print_banner(args.host, args.port, local_ip)

    if not args.no_browser:
        import threading
        def open_browser():
            import time
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{args.port}")
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=False
    )

if __name__ == "__main__":
    main()
