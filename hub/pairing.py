"""
Manager Hub Device Registry & 6-Digit Pairing Engine
Manages device pairing, active pairing codes, and persistent authentication in SQLite.
"""

import sqlite3
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any
from common.config import DEFAULT_DB_FILE
from common.crypto import generate_pairing_code, generate_device_token

logger = logging.getLogger("HubPairing")

class DeviceRegistry:
    """Manages paired devices and active pairing sessions."""
    def __init__(self, db_path: Path = DEFAULT_DB_FILE):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.active_pairing_code: Optional[str] = None
        self.pairing_code_expires_at: float = 0.0

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    hostname TEXT,
                    auth_token TEXT NOT NULL,
                    paired_at REAL NOT NULL,
                    last_seen REAL,
                    status TEXT DEFAULT 'active'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hub_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.commit()

    def get_or_create_pairing_code(self, ttl_seconds: int = 900) -> str:
        """Returns the current active pairing code or generates a new 6-digit code."""
        now = time.time()
        stored_code = self.get_setting("active_pairing_code")
        stored_expiry = self.get_setting("pairing_code_expires_at")
        
        if stored_code and stored_expiry:
            try:
                exp_time = float(stored_expiry)
                if now < exp_time:
                    return stored_code
            except ValueError:
                pass

        new_code = generate_pairing_code()
        exp_time = now + ttl_seconds
        self.set_setting("active_pairing_code", new_code)
        self.set_setting("pairing_code_expires_at", str(exp_time))
        logger.info("Generated new 6-digit pairing code: %s (expires in %ds)", new_code, ttl_seconds)
        return new_code

    def pair_device(self, pairing_code: str, device_id: str, name: str, hostname: str = "") -> Optional[str]:
        """
        Validates the 6-digit pairing code and registers the device.
        Returns the generated 256-bit auth_token if valid, else None.
        """
        now = time.time()
        stored_code = self.get_setting("active_pairing_code")
        stored_expiry = self.get_setting("pairing_code_expires_at")

        if not stored_code or not stored_expiry:
            logger.warning("Pairing rejected: No active pairing code in system")
            return None

        try:
            exp_time = float(stored_expiry)
            if now >= exp_time:
                logger.warning("Pairing rejected: Code expired")
                return None
        except ValueError:
            return None

        if pairing_code.strip() != stored_code:
            logger.warning("Pairing rejected: Invalid code provided (%s)", pairing_code)
            return None

        auth_token = generate_device_token()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO devices (device_id, name, hostname, auth_token, paired_at, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, 'active')
                ON CONFLICT(device_id) DO UPDATE SET
                    name = excluded.name,
                    hostname = excluded.hostname,
                    auth_token = excluded.auth_token,
                    last_seen = excluded.last_seen,
                    status = 'active'
            """, (device_id, name, hostname, auth_token, now, now))
            conn.commit()

        # Invalidate code immediately after successful use for security
        self.set_setting("active_pairing_code", "")
        self.set_setting("pairing_code_expires_at", "0")
        logger.info("Device '%s' (%s) successfully paired with token", name, device_id)
        return auth_token

    def verify_device_token(self, device_id: str, auth_token: str) -> bool:
        """Verifies if the provided auth_token matches the registered device."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT auth_token, status FROM devices WHERE device_id = ?",
                (device_id,)
            )
            row = cursor.fetchone()
            if row and row["status"] == "active" and row["auth_token"] == auth_token:
                conn.execute("UPDATE devices SET last_seen = ? WHERE device_id = ?", (time.time(), device_id))
                conn.commit()
                return True
        return False

    def list_devices(self) -> List[Dict[str, Any]]:
        """Returns all registered devices."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT device_id, name, hostname, paired_at, last_seen, status FROM devices ORDER BY name ASC")
            return [dict(row) for row in cursor.fetchall()]

    def update_last_seen(self, device_id: str):
        with self._get_connection() as conn:
            conn.execute("UPDATE devices SET last_seen = ? WHERE device_id = ?", (time.time(), device_id))
            conn.commit()

    def get_setting(self, key: str) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT value FROM hub_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO hub_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))
            conn.commit()
