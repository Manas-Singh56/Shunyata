"""
Shunyata Network Lockdown Module (lockdown.py)
Lightweight anti-cheat network restriction for participant code execution.

Temporarily blocks outgoing internet access (except localhost) during code execution
to prevent participants from calling external APIs, AI tools, or online compilers.

Supports Windows (netsh), Linux (ufw/iptables), and graceful fallback for demo safety.

Enhanced Features:
- Async-compatible with status callback support
- Thread-safe lockdown operations
- Improved error handling and recovery
- Detailed status reporting for real-time UI updates
- Rule verification and conflict detection
"""

import os
import platform
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import Optional, Callable, Dict, Any

# Thread-safety lock for firewall operations
_lockdown_lock = threading.Lock()
_lockdown_state = {"active": False, "rules_applied": False}


# ============================================================================
# PLATFORM DETECTION & ADMIN CHECKS
# ============================================================================

def is_windows():
    """Check if running on Windows."""
    return platform.system() == "Windows"


def is_admin_windows():
    """Check if script has admin privileges on Windows."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def is_admin_unix():
    """Check if script has root privileges on Unix-like systems."""
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def has_admin():
    """Check if script has necessary privileges for firewall manipulation."""
    if is_windows():
        return is_admin_windows()
    else:
        return is_admin_unix()


def check_firewall_tool():
    """
    Detect available firewall tools on Unix-like systems.
    Returns: "ufw", "iptables", or None
    """
    try:
        subprocess.run(
            ["which", "ufw"],
            capture_output=True,
            check=False,
            timeout=2
        )
        result = subprocess.run(
            ["sudo", "-n", "ufw", "status"],
            capture_output=True,
            check=False,
            timeout=2
        )
        if result.returncode == 0:
            return "ufw"
    except Exception:
        pass
    
    try:
        subprocess.run(
            ["which", "iptables"],
            capture_output=True,
            check=False,
            timeout=2
        )
        return "iptables"
    except Exception:
        pass
    
    return None


def get_lockdown_status() -> Dict[str, Any]:
    """
    Get current lockdown status for status reporting.
    
    Returns:
        dict: Status information including active state, admin privileges, and tool availability
    """
    tool = None
    if not is_windows():
        tool = check_firewall_tool()
    
    return {
        "active": _lockdown_state["active"],
        "rules_applied": _lockdown_state["rules_applied"],
        "platform": platform.system(),
        "has_admin": has_admin(),
        "firewall_tool": "netsh" if is_windows() else tool,
        "demo_mode": not has_admin()
    }


# ============================================================================
# LOGGING
# ============================================================================

def log_lockdown(message, level="INFO", callback: Optional[Callable] = None):
    """
    Print formatted lockdown log messages and optionally call a status callback.
    
    Args:
        message: Log message to display
        level: Log level (INFO, WARN, ERROR)
        callback: Optional callback function for status updates
    """
    formatted_msg = f"[Lockdown] [{level}] {message}"
    print(formatted_msg)
    
    if callback:
        callback({
            "source": "lockdown",
            "level": level,
            "message": message,
            "status": get_lockdown_status()
        })


# ============================================================================
# RULE VERIFICATION
# ============================================================================

def verify_rules_windows() -> bool:
    """Verify that Shunyata firewall rules are active on Windows."""
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=ShunyataBlockAll"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return "ShunyataBlockAll" in result.stdout
    except Exception:
        return False


def verify_rules_unix(tool: str) -> bool:
    """Verify that firewall rules are active on Unix systems."""
    try:
        if tool == "ufw":
            result = subprocess.run(
                ["sudo", "-n", "ufw", "status", "numbered"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return "DENY OUT" in result.stdout
        elif tool == "iptables":
            result = subprocess.run(
                ["sudo", "iptables", "-L", "OUTPUT", "-n"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return "DROP" in result.stdout
    except Exception:
        return False
    return False


# ============================================================================
# WINDOWS FIREWALL RULES (netsh)
# ============================================================================

def enable_lockdown_windows(callback: Optional[Callable] = None):
    """Block all outgoing traffic except localhost on Windows using netsh."""
    log_lockdown("Enabling network restrictions (Windows)...", callback=callback)
    
    if not is_admin_windows():
        log_lockdown(
            "Warning: Not running as admin. Firewall rules not applied. Demo mode.",
            "WARN",
            callback
        )
        _lockdown_state["active"] = True
        _lockdown_state["rules_applied"] = False
        return False
    
    try:
        # First, check if rules already exist and remove them to avoid conflicts
        if verify_rules_windows():
            log_lockdown("Existing Shunyata rules found. Cleaning up...", "INFO", callback)
            disable_lockdown_windows(callback)
        
        # Block all outbound traffic
        result = subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                "name=ShunyataBlockAll",
                "dir=out",
                "action=block",
                "remoteip=0.0.0.0-255.255.255.255",
                "profile=any"
            ],
            check=True,
            capture_output=True,
            timeout=5
        )
        log_lockdown("Blocked all outbound traffic", callback=callback)
        
        # Allow localhost traffic
        subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                "name=ShunyataAllowLocal",
                "dir=out",
                "action=allow",
                "remoteip=127.0.0.1",
                "profile=any"
            ],
            check=True,
            capture_output=True,
            timeout=5
        )
        log_lockdown("Allowed localhost traffic", callback=callback)
        
        # Verify rules were applied
        if verify_rules_windows():
            log_lockdown("Network lockdown verified and active", callback=callback)
            _lockdown_state["active"] = True
            _lockdown_state["rules_applied"] = True
            return True
        else:
            log_lockdown("Failed to verify lockdown rules", "WARN", callback)
            _lockdown_state["active"] = True
            _lockdown_state["rules_applied"] = False
            return False
        
    except subprocess.CalledProcessError as e:
        log_lockdown(f"Error applying firewall rules: {e}", "ERROR", callback)
        _lockdown_state["active"] = False
        _lockdown_state["rules_applied"] = False
        return False
    except Exception as e:
        log_lockdown(f"Unexpected error during enable_lockdown_windows: {e}", "ERROR", callback)
        _lockdown_state["active"] = False
        _lockdown_state["rules_applied"] = False
        return False


def disable_lockdown_windows(callback: Optional[Callable] = None):
    """Remove firewall rules and restore normal network access on Windows."""
    log_lockdown("Disabling network restrictions (Windows)...", callback=callback)
    
    if not is_admin_windows():
        log_lockdown(
            "Warning: Not running as admin. Firewall rules not removed. Demo mode.",
            "WARN",
            callback
        )
        _lockdown_state["active"] = False
        _lockdown_state["rules_applied"] = False
        return True
    
    success = True
    try:
        # Remove block rule
        result = subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "delete", "rule",
                "name=ShunyataBlockAll"
            ],
            check=False,  # Don't fail if rule doesn't exist
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            log_lockdown("Removed outbound block rule", callback=callback)
        
        # Remove allow rule
        result = subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "delete", "rule",
                "name=ShunyataAllowLocal"
            ],
            check=False,
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            log_lockdown("Removed localhost allow rule", callback=callback)
        
        # Verify rules were removed
        if not verify_rules_windows():
            log_lockdown("Network access restored successfully", callback=callback)
            _lockdown_state["active"] = False
            _lockdown_state["rules_applied"] = False
        else:
            log_lockdown("Warning: Some rules may still exist", "WARN", callback)
            success = False
        
    except Exception as e:
        log_lockdown(f"Error removing firewall rules: {e}", "ERROR", callback)
        success = False
    
    _lockdown_state["active"] = False
    return success


# ============================================================================
# UNIX FIREWALL RULES (ufw / iptables)
# ============================================================================

def enable_lockdown_unix(callback: Optional[Callable] = None):
    """Block outbound traffic except localhost on Linux/macOS using ufw or iptables."""
    log_lockdown("Enabling network restrictions (Unix/Linux)...", callback=callback)
    
    if not is_admin_unix():
        log_lockdown(
            "Warning: Not running as root. Firewall rules not applied. Demo mode.",
            "WARN",
            callback
        )
        _lockdown_state["active"] = True
        _lockdown_state["rules_applied"] = False
        return False
    
    tool = check_firewall_tool()
    
    if tool == "ufw":
        try:
            # Check if rules already exist
            if verify_rules_unix(tool):
                log_lockdown("Existing firewall rules found. Cleaning up...", "INFO", callback)
                disable_lockdown_unix(callback)
            
            # Block all outbound
            subprocess.run(
                ["sudo", "ufw", "deny", "out", "from", "any", "to", "any"],
                check=True,
                capture_output=True,
                timeout=5
            )
            log_lockdown("Blocked all outbound traffic (ufw)", callback=callback)
            
            # Allow localhost
            subprocess.run(
                ["sudo", "ufw", "allow", "out", "to", "127.0.0.1"],
                check=True,
                capture_output=True,
                timeout=5
            )
            log_lockdown("Allowed localhost traffic (ufw)", callback=callback)
            
            # Verify
            if verify_rules_unix(tool):
                log_lockdown("Network lockdown verified and active", callback=callback)
                _lockdown_state["active"] = True
                _lockdown_state["rules_applied"] = True
                return True
            
        except subprocess.CalledProcessError as e:
            log_lockdown(f"Error applying ufw rules: {e}", "ERROR", callback)
            _lockdown_state["active"] = False
            _lockdown_state["rules_applied"] = False
            return False
    
    elif tool == "iptables":
        try:
            # Check if rules already exist
            if verify_rules_unix(tool):
                log_lockdown("Existing firewall rules found. Cleaning up...", "INFO", callback)
                disable_lockdown_unix(callback)
            
            # Allow localhost first (order matters)
            subprocess.run(
                ["sudo", "iptables", "-I", "OUTPUT", "1", "-d", "127.0.0.1", "-j", "ACCEPT"],
                check=True,
                capture_output=True,
                timeout=5
            )
            log_lockdown("Allowed localhost traffic (iptables)", callback=callback)
            
            # Block all outbound
            subprocess.run(
                ["sudo", "iptables", "-A", "OUTPUT", "-j", "DROP"],
                check=True,
                capture_output=True,
                timeout=5
            )
            log_lockdown("Blocked all outbound traffic (iptables)", callback=callback)
            
            # Verify
            if verify_rules_unix(tool):
                log_lockdown("Network lockdown verified and active", callback=callback)
                _lockdown_state["active"] = True
                _lockdown_state["rules_applied"] = True
                return True
            
        except subprocess.CalledProcessError as e:
            log_lockdown(f"Error applying iptables rules: {e}", "ERROR", callback)
            _lockdown_state["active"] = False
            _lockdown_state["rules_applied"] = False
            return False
    
    else:
        log_lockdown(
            "No firewall tool found (ufw/iptables). Skipping firewall rules.",
            "WARN",
            callback
        )
        _lockdown_state["active"] = True
        _lockdown_state["rules_applied"] = False
        return False
    
    return False


def disable_lockdown_unix(callback: Optional[Callable] = None):
    """Remove firewall rules and restore normal network access on Unix."""
    log_lockdown("Disabling network restrictions (Unix/Linux)...", callback=callback)
    
    if not is_admin_unix():
        log_lockdown(
            "Warning: Not running as root. Firewall rules not removed. Demo mode.",
            "WARN",
            callback
        )
        _lockdown_state["active"] = False
        _lockdown_state["rules_applied"] = False
        return True
    
    tool = check_firewall_tool()
    success = True
    
    if tool == "ufw":
        try:
            subprocess.run(
                ["sudo", "ufw", "delete", "deny", "out", "from", "any", "to", "any"],
                check=False,
                capture_output=True,
                timeout=5
            )
            subprocess.run(
                ["sudo", "ufw", "delete", "allow", "out", "to", "127.0.0.1"],
                check=False,
                capture_output=True,
                timeout=5
            )
            
            if not verify_rules_unix(tool):
                log_lockdown("Removed ufw rules - network access restored", callback=callback)
            else:
                log_lockdown("Warning: Some ufw rules may still exist", "WARN", callback)
                success = False
                
        except Exception as e:
            log_lockdown(f"Error removing ufw rules: {e}", "ERROR", callback)
            success = False
    
    elif tool == "iptables":
        try:
            # Remove rules (may need multiple attempts if rules were duplicated)
            for _ in range(5):  # Try up to 5 times to catch duplicate rules
                result1 = subprocess.run(
                    ["sudo", "iptables", "-D", "OUTPUT", "-j", "DROP"],
                    check=False,
                    capture_output=True,
                    timeout=5
                )
                result2 = subprocess.run(
                    ["sudo", "iptables", "-D", "OUTPUT", "-d", "127.0.0.1", "-j", "ACCEPT"],
                    check=False,
                    capture_output=True,
                    timeout=5
                )
                if result1.returncode != 0 and result2.returncode != 0:
                    break  # No more rules to remove
            
            if not verify_rules_unix(tool):
                log_lockdown("Removed iptables rules - network access restored", callback=callback)
            else:
                log_lockdown("Warning: Some iptables rules may still exist", "WARN", callback)
                success = False
                
        except Exception as e:
            log_lockdown(f"Error removing iptables rules: {e}", "ERROR", callback)
            success = False
    
    _lockdown_state["active"] = False
    _lockdown_state["rules_applied"] = False if success else _lockdown_state["rules_applied"]
    return success


# ============================================================================
# PUBLIC API
# ============================================================================

def enable(cjs_ip: Optional[str] = None, callback: Optional[Callable] = None) -> bool:
    """
    Temporarily restrict outgoing internet access during code execution.
    Thread-safe implementation.
    
    Args:
        cjs_ip: IP of Central Judge Server (for future whitelist feature)
        callback: Optional callback function for status updates
        
    Returns:
        bool: True if lockdown was successfully applied, False otherwise
    """
    with _lockdown_lock:
        if _lockdown_state["active"]:
            log_lockdown("Lockdown already active", "INFO", callback)
            return _lockdown_state["rules_applied"]
        
        if is_windows():
            return enable_lockdown_windows(callback)
        else:
            return enable_lockdown_unix(callback)


def release(callback: Optional[Callable] = None) -> bool:
    """
    Restore normal network access after code execution.
    Thread-safe implementation.
    
    Args:
        callback: Optional callback function for status updates
        
    Returns:
        bool: True if lockdown was successfully released, False otherwise
    """
    with _lockdown_lock:
        if not _lockdown_state["active"]:
            log_lockdown("Lockdown not active", "INFO", callback)
            return True
        
        if is_windows():
            return disable_lockdown_windows(callback)
        else:
            return disable_lockdown_unix(callback)


# Legacy compatibility aliases
def enable_lockdown(cjs_ip: Optional[str] = None):
    """Legacy alias for enable(). For backward compatibility."""
    return enable(cjs_ip)


def disable_lockdown():
    """Legacy alias for release(). For backward compatibility."""
    return release()


@contextmanager
def lockdown_context(callback: Optional[Callable] = None):
    """
    Context manager for easy lockdown usage in executor.py.
    Thread-safe and ensures cleanup even if exceptions occur.
    
    Args:
        callback: Optional callback function for status updates
    
    Example:
        from lockdown import lockdown_context
        with lockdown_context():
            run_code_locally(user_code, problem_id)
    """
    enabled = enable(callback=callback)
    try:
        yield enabled
    finally:
        release(callback=callback)


@contextmanager
def async_lockdown_context(status_callback: Optional[Callable] = None):
    """
    Async-compatible context manager with detailed status reporting.
    Perfect for use with the new async executor.
    
    Args:
        status_callback: Callback function that receives status updates
    
    Example:
        def update_status(msg):
            print(f"Lockdown: {msg}")
        
        with async_lockdown_context(update_status):
            # Run code with network restrictions
            pass
    """
    def wrapped_callback(data):
        if status_callback:
            status_callback(data["message"])
    
    enabled = enable(callback=wrapped_callback)
    try:
        yield {"enabled": enabled, "status": get_lockdown_status()}
    finally:
        release(callback=wrapped_callback)


# ============================================================================
# EMERGENCY CLEANUP
# ============================================================================

def emergency_cleanup():
    """
    Emergency function to forcefully remove all Shunyata firewall rules.
    Use this if rules are stuck after abnormal termination.
    """
    log_lockdown("Performing emergency cleanup of firewall rules...", "WARN")
    
    with _lockdown_lock:
        _lockdown_state["active"] = False
        _lockdown_state["rules_applied"] = False
        
        if is_windows():
            disable_lockdown_windows()
        else:
            disable_lockdown_unix()
    
    log_lockdown("Emergency cleanup complete", "INFO")


# ============================================================================
# DEMO & TESTING
# ============================================================================

if __name__ == "__main__":
    import time
    
    # Simple test: enable lockdown for 5 seconds, then disable
    log_lockdown("Starting lockdown module test...")
    log_lockdown(f"Platform: {platform.system()}")
    log_lockdown(f"Admin privileges: {has_admin()}")
    
    status = get_lockdown_status()
    log_lockdown(f"Initial status: {status}")
    
    # Test with callback
    def test_callback(data):
        print(f"  -> Callback received: {data['message']}")
    
    log_lockdown("\n=== Testing enable/release with callback ===")
    success = enable(callback=test_callback)
    log_lockdown(f"Enable result: {success}")
    log_lockdown(f"Current status: {get_lockdown_status()}")
    
    log_lockdown("Lockdown active. Sleeping for 3 seconds...")
    time.sleep(3)
    
    release(callback=test_callback)
    log_lockdown(f"Final status: {get_lockdown_status()}")
    
    # Test context manager
    log_lockdown("\n=== Testing context manager ===")
    with async_lockdown_context(lambda msg: print(f"  -> {msg}")):
        log_lockdown("Inside context manager - network should be locked")
        time.sleep(2)
    
    log_lockdown("\nTest complete!")
    log_lockdown(f"Final status: {get_lockdown_status()}")