"""
Shunyata Network Lockdown Module (lockdown.py)
"""
import os
import platform
import subprocess
import threading
from contextlib import contextmanager

_lockdown_lock = threading.Lock()
_lockdown_active = False

def is_windows():
    return platform.system() == "Windows"

def has_admin():
    try:
        if is_windows():
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        return os.geteuid() == 0
    except Exception:
        return False

def enable_lockdown_windows():
    subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", "name=ShunyataBlockAll", "dir=out", "action=block"], check=True, capture_output=True)
    subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", "name=ShunyataAllowLocal", "dir=out", "action=allow", "remoteip=127.0.0.1"], check=True, capture_output=True)

def disable_lockdown_windows():
    subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=ShunyataBlockAll"], check=False, capture_output=True)
    subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=ShunyataAllowLocal"], check=False, capture_output=True)

def enable_lockdown_unix():
    # This is a simplified example for iptables
    subprocess.run(["sudo", "iptables", "-I", "OUTPUT", "1", "-d", "127.0.0.1", "-j", "ACCEPT"], check=True)
    subprocess.run(["sudo", "iptables", "-A", "OUTPUT", "-j", "DROP"], check=True)

def disable_lockdown_unix():
    subprocess.run(["sudo", "iptables", "-D", "OUTPUT", "-j", "DROP"], check=False)
    subprocess.run(["sudo", "iptables", "-D", "OUTPUT", "-d", "127.0.0.1", "-j", "ACCEPT"], check=False)

def enable():
    global _lockdown_active
    with _lockdown_lock:
        if _lockdown_active or not has_admin():
            return
        try:
            if is_windows():
                enable_lockdown_windows()
            else:
                enable_lockdown_unix()
            _lockdown_active = True
            print("[Lockdown] Network restrictions enabled.")
        except Exception as e:
            print(f"[Lockdown] Failed to enable lockdown: {e}")

def release():
    global _lockdown_active
    with _lockdown_lock:
        if not _lockdown_active or not has_admin():
            return
        try:
            if is_windows():
                disable_lockdown_windows()
            else:
                disable_lockdown_unix()
            _lockdown_active = False
            print("[Lockdown] Network restrictions released.")
        except Exception as e:
            print(f"[Lockdown] Failed to release lockdown: {e}")

@contextmanager
def lockdown_context():
    enable()
    try:
        yield
    finally:
        release()