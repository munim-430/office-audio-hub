"""
PyInstaller Build Script for EmployeeAgent.exe
Bundles Employee Agent into a single-file portable Windows executable.
"""

import sys
import subprocess
from pathlib import Path

def build():
    root_dir = Path(__file__).parent.parent
    output_dir = root_dir / "dist"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "EmployeeAgent",
        "--collect-all", "sounddevice",
        "--collect-all", "pyogg",
        "--collect-all", "pystray",
        "--collect-all", "PIL",
        "--hidden-import", "cffi",
        "--hidden-import", "queue",
        "--hidden-import", "sqlite3",
        "--hidden-import", "websockets",
        str(root_dir / "run_agent.py")
    ]

    # For Windows production, add --noconsole to suppress command prompt window
    if sys.platform == "win32":
        cmd.append("--noconsole")

    print("Running command:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(root_dir))
    print(f"\n✅ Build complete: {output_dir / 'EmployeeAgent'}")

if __name__ == "__main__":
    build()
