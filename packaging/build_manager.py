"""
PyInstaller Build Script for ManagerHub.exe
Bundles Manager Hub into a single-file portable Windows executable.
"""

import sys
import subprocess
from pathlib import Path

def build():
    root_dir = Path(__file__).parent.parent
    static_dir = root_dir / "hub" / "static"
    output_dir = root_dir / "dist"

    sep = ";" if sys.platform == "win32" else ":"
    add_data_arg = f"{static_dir}{sep}hub/static"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "ManagerHub",
        "--add-data", add_data_arg,
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        str(root_dir / "run_hub.py")
    ]

    print("Running command:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(root_dir))
    print(f"\n✅ Build complete: {output_dir / 'ManagerHub'}")

if __name__ == "__main__":
    build()
