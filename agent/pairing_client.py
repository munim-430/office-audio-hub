"""
Employee Agent Pairing Client
Handles first-time 6-digit code submission and auth token persistence in agent_config.json.
"""

import os
import json
import uuid
import socket
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import urllib.request
import urllib.error

logger = logging.getLogger("AgentPairing")

DEFAULT_CONFIG_PATH = Path("agent_config.json")

class AgentConfig:
    def __init__(
        self,
        hub_url: str,
        device_id: str,
        device_name: str,
        auth_token: str
    ):
        self.hub_url = hub_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.auth_token = auth_token

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hub_url": self.hub_url,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "auth_token": self.auth_token
        }

    def save(self, path: Path = DEFAULT_CONFIG_PATH):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Saved agent configuration to %s", path)

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> Optional["AgentConfig"]:
        path = Path(path)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                hub_url=data["hub_url"],
                device_id=data["device_id"],
                device_name=data.get("device_name", data["device_id"]),
                auth_token=data["auth_token"]
            )
        except Exception as e:
            logger.error("Failed to load agent config from %s: %s", path, e)
            return None

def pair_with_hub(
    hub_url: str,
    pairing_code: str,
    device_name: Optional[str] = None,
    device_id: Optional[str] = None,
    config_path: Path = DEFAULT_CONFIG_PATH
) -> Optional[AgentConfig]:
    """Submits 6-digit pairing code to Manager Hub and stores issued token."""
    hub_url = hub_url.rstrip("/")
    hostname = socket.gethostname()
    if not device_name:
        device_name = f"Laptop-{hostname}"
    if not device_id:
        device_id = f"AGENT-{uuid.uuid4().hex[:8].upper()}"

    payload = json.dumps({
        "pairing_code": pairing_code.strip(),
        "device_id": device_id,
        "name": device_name,
        "hostname": hostname
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{hub_url}/api/pair",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            auth_token = data.get("auth_token")
            if auth_token:
                cfg = AgentConfig(
                    hub_url=hub_url,
                    device_id=device_id,
                    device_name=device_name,
                    auth_token=auth_token
                )
                cfg.save(config_path)
                return cfg
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        logger.error("Pairing HTTP error: %s (%s)", e.code, err_msg)
    except Exception as e:
        logger.error("Pairing network error: %s", e)

    return None
