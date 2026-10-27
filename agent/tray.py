"""
Employee Agent System Tray Indicator
Discreet system tray icon displaying live connection status and clean exit handler.
Falls back gracefully when headless or display server is absent.
"""

import sys
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger("AgentTray")

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except (ImportError, Exception) as exc:
    TRAY_AVAILABLE = False
    logger.info("pystray or Pillow not available (%s); running headless", exc)

def create_tray_icon_image(color: str = "#10b981"):
    """Generates a dynamic 64x64 icon with a colored microphone dot."""
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Background circle
    draw.ellipse((8, 8, 56, 56), fill="#0f172a", outline="#334155", width=2)
    # Indicator dot
    draw.ellipse((22, 22, 42, 42), fill=color)
    return img

class SystemTrayManager:
    """Manages the system tray icon lifecycle."""
    def __init__(self, device_name: str, on_exit: Optional[Callable[[], None]] = None):
        self.device_name = device_name
        self.on_exit = on_exit
        self.icon = None
        self.current_status = "Initializing..."

    def start(self):
        if not TRAY_AVAILABLE:
            logger.info("System tray disabled (headless environment)")
            return

        def _run():
            try:
                image = create_tray_icon_image("#10b981")
                menu = pystray.Menu(
                    pystray.MenuItem(f"Keystone Agent: {self.device_name}", None, enabled=False),
                    pystray.MenuItem(lambda text: f"Status: {self.current_status}", None, enabled=False),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Exit", self._handle_exit)
                )
                self.icon = pystray.Icon("KeystoneAgent", image, f"Keystone Agent - {self.device_name}", menu)
                self.icon.run()
            except Exception as e:
                logger.warning("Could not launch system tray icon: %s", e)

        tray_thread = threading.Thread(target=_run, daemon=True)
        tray_thread.start()

    def update_status(self, status: str):
        self.current_status = status
        if self.icon:
            try:
                self.icon.title = f"Keystone Agent ({self.device_name}): {status}"
                if "Streaming" in status:
                    self.icon.icon = create_tray_icon_image("#10b981")  # Emerald green
                elif "Buffering" in status or "Offline" in status:
                    self.icon.icon = create_tray_icon_image("#f59e0b")  # Amber
                else:
                    self.icon.icon = create_tray_icon_image("#64748b")  # Slate gray
            except Exception:
                pass

    def _handle_exit(self, icon, item):
        logger.info("Exit requested from system tray icon")
        if self.icon:
            self.icon.stop()
        if self.on_exit:
            self.on_exit()
        sys.exit(0)

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
