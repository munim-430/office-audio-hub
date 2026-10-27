"""
Windows Startup & Auto-Launch Integration for Employee Agent
Allows the portable agent to automatically start on user login with zero admin rights.
"""

import sys
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("AgentStartup")

def install_windows_startup(exe_path: Optional[str] = None, name: str = "KeystoneEmployeeAgent") -> bool:
    """Adds the executable to the Windows HKCU Run registry key."""
    if sys.platform != "win32":
        logger.info("Startup registration skipped (non-Windows platform)")
        return False

    try:
        import winreg
        if not exe_path:
            exe_path = sys.executable

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, f'"{exe_path}"')
        winreg.CloseKey(key)
        logger.info("Successfully registered '%s' in Windows startup registry.", name)
        return True
    except Exception as e:
        logger.warning("Could not register Windows startup registry key: %s", e)
        return False

def uninstall_windows_startup(name: str = "KeystoneEmployeeAgent") -> bool:
    """Removes the executable from the Windows HKCU Run registry key."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, name)
        winreg.CloseKey(key)
        logger.info("Removed '%s' from Windows startup registry.", name)
        return True
    except Exception as e:
        logger.debug("Registry value not found or cannot remove: %s", e)
        return False
