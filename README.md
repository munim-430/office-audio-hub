# 🎙️ Keystone Office Audio Hub & Streamer

> **A dual-executable, local-first 24/7 office microphone recording and live streaming system.**
> Designed for continuous multi-workstation monitoring, sub-second live audio taps, and local 90-minute chunk archiving exclusively on the Manager's PC hard drive.

---

## 🌟 Key Architectural Features

1. **Dual Standalone Executables (`.exe`):**
   - **`ManagerHub.exe`**: Runs on the Manager's PC. Hosts the Web Dashboard, handles 6-digit device pairing, ingests 24/7 continuous audio streams, rotates 90-minute chunks, and provides instant live listening.
   - **`EmployeeAgent.exe`**: Portable agent on office employee laptops. Runs silently in the background with a discreet system tray icon. Automatically starts with Windows.
2. **Sub-Second Live Audio Tapping:**
   - Employee agents stream continuous 20ms Opus frames over persistent WebSockets.
   - The Manager Web Dashboard taps into any employee's live audio feed on demand via the browser's native **Web Audio API** with latency <500ms and live oscilloscope waveform visualization.
3. **100% Local 90-Minute Chunk Archiving (Zero Cloud / No Google Drive):**
   - Recordings are organized chronologically on the Manager's local disk: `storage/audio/<device_id>/<YYYY-MM-DD>/<chunk_id>.opus`.
   - Each frame record flushes immediately to disk; abrupt power loss or reboot leaves every single second of audio intact and playable.
   - Built-in on-demand WAV rendering allows in-browser playback and direct `.wav` export.
4. **One-Time 6-Digit Pairing Code Handshake:**
   - No complex certificates or manual IP matching.
   - The Manager Dashboard displays an ephemeral 6-digit pairing code (e.g. `834-192`).
   - The Employee Agent prompts for this code on first launch, exchanges a 256-bit mutual auth token, saves `agent_config.json`, and thereafter reconnects silently without user intervention.
5. **Offline Ring Buffer with Auto-Backfill:**
   - If office Wi-Fi drops, the Employee Agent caches audio into an encrypted local SQLite WAL ring buffer (up to 3 days / 2 GB).
   - Upon reconnection, live streaming resumes with immediate priority, while a background worker backfills missed chunks smoothly.

---

## 🏗️ Repository Layout

```
office-audio-hub/
├── common/
│   ├── config.py             # Shared ports, audio sample rates, chunk limits
│   ├── protocol.py           # Binary packet framing (Magic 0xA0, types, CRC/timestamps)
│   ├── crypto.py             # 6-digit pairing generator, tokens, PBKDF2 password hashing
│   └── audio_format.py       # Opus encoder/decoder wrapper, PCM converters, RMS VU metering
├── hub/
│   ├── server.py             # FastAPI REST & WebSocket server
│   ├── pairing.py            # Device registry & 6-digit pairing state engine
│   ├── storage.py            # 90-minute chunk writer & on-demand WAV exporter
│   ├── stream_manager.py     # Real-time WebSocket demuxer & live audio broadcaster
│   └── static/
│       ├── index.html        # Responsive executive web dashboard
│       ├── app.js            # Web Audio API live streaming player & chunk browser
│       └── style.css         # Modern dark-mode console theme & VU animations
├── agent/
│   ├── capture.py            # sounddevice PortAudio with WASAPI supervisor loop
│   ├── client.py             # Continuous streaming client, reconnect loop & backfill
│   ├── ring_buffer.py        # 3-day / 2 GB SQLite WAL offline ring buffer
│   ├── pairing_client.py     # First-run 6-digit code submission & token persistence
│   ├── startup.py            # Zero-UAC Windows HKCU Run auto-startup registrar
│   └── tray.py               # pystray system tray icon with live connection states
├── packaging/
│   ├── build_manager.py      # PyInstaller onefile build script for ManagerHub.exe
│   └── build_agent.py        # PyInstaller onefile build script for EmployeeAgent.exe
├── tests/                    # 19 comprehensive automated unit and E2E tests
├── run_hub.py                # Standalone entry point for Manager Hub
├── run_agent.py              # Standalone entry point for Employee Agent
├── build_windows.bat         # 1-click Windows compilation script
├── start_manager.bat         # Quick launcher for Manager Hub
├── start_agent.bat           # Quick launcher for Employee Agent
└── requirements.txt          # Python dependencies
```

---

## 🚀 Quickstart Guide

### 1. Running on Manager's PC

```bash
# In office-audio-hub directory:
python run_hub.py
```
* Manager Hub will start on `http://0.0.0.0:8080` and automatically open your default browser.
* On first run, choose your Manager Admin Password to lock the dashboard.
* Click **➕ Pair Employee Laptop** to view the active 6-digit pairing code.

### 2. Running on Employee Workstations

```bash
# In office-audio-hub directory:
python run_agent.py
```
* On first launch, the agent will prompt for:
  - **Manager Hub URL**: e.g. `http://192.168.1.50:8080` (or local IP displayed on Manager console)
  - **6-Digit Pairing Code**: The code from the Manager Dashboard
  - **Workstation Name**: e.g. `Reception Desk`
* Once paired, the agent runs in the system tray (`🟢 Active & Streaming`).

---

## 📦 Compiling Portable Windows Executables (`.exe`)

Run `build_windows.bat` on any 64-bit Windows machine, or manually via Python:

```bash
# Compile Manager Hub (ManagerHub.exe)
python packaging/build_manager.py

# Compile Employee Agent (EmployeeAgent.exe)
python packaging/build_agent.py
```

The resulting standalone binaries will be placed in the `dist/` directory:
- `dist/ManagerHub.exe` (~28 MB single-file)
- `dist/EmployeeAgent.exe` (~22 MB single-file, windowless with system tray icon)

---

## 🧪 Automated Test Suite

All modules are covered by 19 automated tests (Unit, Storage, Protocol, Crypto, and full live E2E streaming):

```bash
pytest tests/ -v
```

Output:
```
tests/test_crypto_pairing.py::test_pairing_code_format PASSED
tests/test_crypto_pairing.py::test_device_token_entropy PASSED
tests/test_crypto_pairing.py::test_password_hashing_and_verification PASSED
tests/test_crypto_pairing.py::test_session_token_entropy PASSED
tests/test_dashboard_api.py::test_auth_status_initial PASSED
tests/test_dashboard_api.py::test_auth_setup_and_login PASSED
tests/test_dashboard_api.py::test_pairing_api_workflow PASSED
tests/test_dashboard_api.py::test_static_index_serving PASSED
tests/test_e2e_stream.py::test_full_e2e_streaming_and_backfill PASSED
tests/test_protocol.py::test_encode_decode_audio_frame PASSED
tests/test_protocol.py::test_heartbeat_ping_pong PASSED
tests/test_protocol.py::test_invalid_magic_header PASSED
tests/test_protocol.py::test_truncated_data PASSED
tests/test_protocol.py::test_long_device_id_truncation PASSED
tests/test_ring_buffer.py::test_ring_buffer_push_and_peek PASSED
tests/test_ring_buffer.py::test_ring_buffer_retention_purge PASSED
tests/test_storage_chunks.py::test_device_registry_lifecycle PASSED
tests/test_storage_chunks.py::test_chunk_recording_and_rotation PASSED
tests/test_storage_chunks.py::test_export_chunk_to_wav PASSED
======================== 19 passed, 1 warning in 3.64s =========================
```
