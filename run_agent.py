#!/usr/bin/env python3
"""
Employee Agent Entry Point (EmployeeAgent.exe)
Unattended 24/7 background audio capture and streaming agent with system tray indicator.
"""

import sys
import os
import time
import socket
import argparse
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("EmployeeAgent")

from agent.pairing_client import AgentConfig, pair_with_hub, DEFAULT_CONFIG_PATH
from agent.client import EmployeeAgentClient
from agent.ring_buffer import OfflineRingBuffer
from agent.tray import SystemTrayManager

def prompt_first_time_pairing(config_path: Path) -> AgentConfig:
    print("\n" + "="*60)
    print("      🎙️  KEYSTONE OVERSEAS — EMPLOYEE AGENT SETUP        ")
    print("="*60)
    print("  First-time pairing required with Manager Hub.")
    print("  Look at the Manager Dashboard for the 6-Digit Pairing Code.\n")

    hub_url = input("  Enter Manager Hub URL [e.g. http://192.168.1.50:8080]: ").strip()
    if not hub_url:
        print("  ❌ Manager Hub URL is required.")
        sys.exit(1)

    code = input("  Enter 6-Digit Pairing Code: ").strip()
    if not code:
        print("  ❌ Pairing code is required.")
        sys.exit(1)

    hostname = socket.gethostname()
    default_name = f"Desk-{hostname}"
    device_name = input(f"  Enter Workstation Name [{default_name}]: ").strip() or default_name

    print("\n  Pairing with Manager Hub...")
    cfg = pair_with_hub(hub_url=hub_url, pairing_code=code, device_name=device_name, config_path=config_path)
    if not cfg:
        print("  ❌ Pairing failed! Check your Hub URL and ensure the code has not expired.")
        sys.exit(1)

    print(f"  ✅ Pairing Successful! Workstation registered as: {cfg.device_id}")
    print("="*60 + "\n")
    return cfg

def main():
    parser = argparse.ArgumentParser(description="Office Audio Hub - Employee Agent")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to agent_config.json")
    parser.add_argument("--hub-url", help="Direct Manager Hub URL (for automated pairing)")
    parser.add_argument("--code", help="6-digit pairing code (for automated pairing)")
    parser.add_argument("--name", help="Device name / label")
    parser.add_argument("--no-tray", action="store_true", help="Disable system tray icon")
    parser.add_argument("--test-mode", action="store_true", help="Run with synthetic audio capture")
    args = parser.parse_args()

    config_path = Path(args.config)
    cfg = AgentConfig.load(config_path)

    # Automated pairing via CLI flags
    if not cfg and args.hub_url and args.code:
        cfg = pair_with_hub(
            hub_url=args.hub_url,
            pairing_code=args.code,
            device_name=args.name,
            config_path=config_path
        )

    # Interactive prompt if still no config
    if not cfg:
        cfg = prompt_first_time_pairing(config_path)

    ring_buffer = OfflineRingBuffer(db_path=Path("agent_cache.db"))
    client = EmployeeAgentClient(config=cfg, ring_buffer=ring_buffer, test_mode=args.test_mode)

    tray = None
    if not args.no_tray:
        tray = SystemTrayManager(device_name=cfg.device_name, on_exit=client.stop)
        tray.start()
        client.status_callback = tray.update_status

    try:
        client.start()
        logger.info("Employee Agent running. Press Ctrl+C to terminate.")
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Termination signal received. Shutting down...")
    finally:
        client.stop()
        if tray:
            tray.stop()
        logger.info("Employee Agent successfully shut down.")

if __name__ == "__main__":
    main()
