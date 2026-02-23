"""
core/status.py
Hardware status checks: Wi-Fi, Ethernet, and Bluetooth.
"""

import subprocess


def _run_command(cmd, timeout=None):
    """Runs a shell command and returns output as a string. On error — ''."""
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            timeout=timeout
        )
        return out.decode("utf-8", errors="ignore").strip()
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""


def is_ethernet_connected() -> bool:
    """True if Ethernet (eth0) is connected and has an IP address."""
    link = _run_command(["ip", "link", "show", "eth0"])
    if "state UP" not in link:
        return False
    addr = _run_command(["ip", "addr", "show", "eth0"])
    return "inet " in addr


def is_wifi_connected() -> bool:
    """True if Wi-Fi is connected (iwgetid returned an SSID)."""
    ssid = _run_command(["iwgetid", "-r"])
    return ssid != ""


def is_bluetooth_on() -> bool:
    """True if Bluetooth adapter hci0 is active."""
    out = _run_command(["hciconfig", "hci0"])
    if not out:
        return False
    return "UP RUNNING" in out.upper()