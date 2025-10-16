"""
Shunyata Client Environment Agent (CEA)
Main controller for the participant-side client.

Runs a local Flask web server on http://localhost:8000 to serve the contest UI.
Communicates with the Central Judge Server (CJS) over LAN for problem fetching and code submission.
Integrates local code execution via executor.py and optional network lockdown via lockdown.py.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from flask import Flask, render_template, request, jsonify
import requests

# Import local modules (executor and lockdown)
# These are expected to exist in the same directory
try:
    from executor import run_code_locally
except ImportError:
    print("Warning: executor.py not found. Local testing will not work.")
    run_code_locally = None

try:
    from lockdown import enable_lockdown, disable_lockdown
except ImportError:
    print("Warning: lockdown.py not found. Lockdown features disabled.")
    enable_lockdown = None
    disable_lockdown = None


# Flask app setup
app = Flask(__name__, template_folder="templates")

# Global variables
CJS_IP = None  # Central Judge Server IP (passed via command line)
CJS_PORT = 5000  # Default CJS port
LOCKDOWN_ACTIVE = False  # Track lockdown state


def get_cjs_url():
    """Construct the base URL for the CJS."""
    if not CJS_IP:
        return None
    return f"http://{CJS_IP}:{CJS_PORT}"


def log(message, level="INFO"):
    """Simple console logging."""
    print(f"[{level}] {message}")


# ============================================================================
# ROUTES
# ============================================================================

@app.route("/")
def index():
    """Serve the main participant UI (index.html)."""
    log(f"GET / - Serving main page")
    return render_template("index.html")


@app.route("/problems", methods=["GET"])
def get_problems():
    """
    Fetch the list of available problems from the CJS.
    Returns a list of problems with titles, statements, and sample test cases.
    """
    log("GET /problems - Fetching problems from CJS")
    
    if not CJS_IP:
        return jsonify({"error": "CJS IP not configured"}), 400
    
    try:
        cjs_url = get_cjs_url()
        response = requests.get(f"{cjs_url}/problems", timeout=5)
        response.raise_for_status()
        problems = response.json()
        log(f"Successfully fetched {len(problems)} problem(s) from CJS")
        return jsonify(problems), 200
    except requests.exceptions.ConnectionError:
        error_msg = "Cannot reach Central Judge Server. Check CJS IP and connectivity."
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 503
    except requests.exceptions.Timeout:
        error_msg = "CJS request timed out."
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 503
    except Exception as e:
        error_msg = f"Error fetching problems: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


@app.route("/run-local", methods=["POST"])
def run_local_tests():
    """
    Accept code snippet + problem ID, run locally against sample test cases.
    Returns test results to the participant for instant feedback.
    """
    log("POST /run-local - Running local tests")
    
    if not run_code_locally:
        return jsonify({"error": "Local executor not available"}), 503
    
    try:
        data = request.get_json()
        source_code = data.get("code", "")
        problem_id = data.get("problem_id", "")
        
        if not source_code or not problem_id:
            return jsonify({"error": "Missing code or problem_id"}), 400
        
        log(f"Running local tests for problem {problem_id}")
        
        # Call executor to run code locally
        result = run_code_locally(source_code, problem_id)
        
        log(f"Local test completed for problem {problem_id}")
        return jsonify(result), 200
        
    except Exception as e:
        error_msg = f"Error running local tests: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


@app.route("/submit", methods=["POST"])
def submit_code():
    """
    Send final code submission to the CJS for official judging.
    Receives verdict (Accepted, Wrong Answer, etc.) and returns to UI.
    """
    log("POST /submit - Submitting code to CJS")
    
    if not CJS_IP:
        return jsonify({"error": "CJS IP not configured"}), 400
    
    try:
        data = request.get_json()
        source_code = data.get("code", "")
        problem_id = data.get("problem_id", "")
        participant_name = data.get("participant_name", "anonymous")
        
        if not source_code or not problem_id:
            return jsonify({"error": "Missing code or problem_id"}), 400
        
        log(f"Submitting code for problem {problem_id} from {participant_name}")
        
        # Prepare submission payload
        submission = {
            "code": source_code,
            "problem_id": problem_id,
            "participant_name": participant_name
        }
        
        # Send to CJS
        cjs_url = get_cjs_url()
        response = requests.post(
            f"{cjs_url}/submit",
            json=submission,
            timeout=10
        )
        response.raise_for_status()
        
        result = response.json()
        log(f"Submission verdict received: {result.get('verdict', 'unknown')}")
        return jsonify(result), 200
        
    except requests.exceptions.ConnectionError:
        error_msg = "Cannot reach Central Judge Server for submission."
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 503
    except requests.exceptions.Timeout:
        error_msg = "CJS submission request timed out."
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 503
    except Exception as e:
        error_msg = f"Error submitting code: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


@app.route("/scoreboard", methods=["GET"])
def get_scoreboard():
    """
    Fetch live scoreboard data from the CJS.
    Displays current standings for all participants.
    """
    log("GET /scoreboard - Fetching scoreboard from CJS")
    
    if not CJS_IP:
        return jsonify({"error": "CJS IP not configured"}), 400
    
    try:
        cjs_url = get_cjs_url()
        response = requests.get(f"{cjs_url}/scoreboard", timeout=5)
        response.raise_for_status()
        scoreboard = response.json()
        log("Successfully fetched scoreboard from CJS")
        return jsonify(scoreboard), 200
    except requests.exceptions.ConnectionError:
        error_msg = "Cannot reach Central Judge Server for scoreboard."
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 503
    except Exception as e:
        error_msg = f"Error fetching scoreboard: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


@app.route("/lockdown", methods=["POST"])
def toggle_lockdown():
    """
    Enable or disable network lockdown mode.
    Lockdown mode blocks internet access except to CJS (via firewall rules).
    Requires admin privileges on Windows.
    """
    global LOCKDOWN_ACTIVE
    
    log("POST /lockdown - Toggling lockdown mode")
    
    if not enable_lockdown or not disable_lockdown:
        return jsonify({"error": "Lockdown module not available"}), 503
    
    try:
        data = request.get_json()
        action = data.get("action", "").lower()  # "enable" or "disable"
        
        if action == "enable":
            if LOCKDOWN_ACTIVE:
                return jsonify({"message": "Lockdown already active"}), 200
            
            log("Activating network lockdown")
            enable_lockdown(CJS_IP)
            LOCKDOWN_ACTIVE = True
            return jsonify({"message": "Lockdown enabled"}), 200
            
        elif action == "disable":
            if not LOCKDOWN_ACTIVE:
                return jsonify({"message": "Lockdown not active"}), 200
            
            log("Disabling network lockdown")
            disable_lockdown()
            LOCKDOWN_ACTIVE = False
            return jsonify({"message": "Lockdown disabled"}), 200
            
        else:
            return jsonify({"error": "Invalid action (use 'enable' or 'disable')"}), 400
            
    except PermissionError:
        error_msg = "Admin privileges required for lockdown. Run as Administrator."
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 403
    except Exception as e:
        error_msg = f"Error toggling lockdown: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


@app.route("/status", methods=["GET"])
def get_status():
    """
    Return current agent status (health check).
    Useful for debugging and verifying agent is running.
    """
    status = {
        "agent_running": True,
        "cjs_ip": CJS_IP,
        "cjs_url": get_cjs_url(),
        "lockdown_active": LOCKDOWN_ACTIVE,
        "executor_available": run_code_locally is not None,
        "lockdown_available": enable_lockdown is not None
    }
    return jsonify(status), 200


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Parse command-line arguments and start the Flask server."""
    global CJS_IP
    
    parser = argparse.ArgumentParser(
        description="Shunyata Client Environment Agent - Local contest client"
    )
    parser.add_argument(
        "--server-ip",
        type=str,
        required=True,
        help="IP address of the Central Judge Server (e.g., 192.168.1.10)"
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=5000,
        help="Port of the Central Judge Server (default: 5000)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Local port for this agent to listen on (default: 8000)"
    )
    
    args = parser.parse_args()
    
    CJS_IP = args.server_ip
    
    log(f"Shunyata Client Environment Agent starting...")
    log(f"Central Judge Server: {get_cjs_url()}")
    log(f"Local server: http://127.0.0.1:{args.port}")
    log(f"Open browser to http://localhost:{args.port}")
    log("")
    
    # Start Flask app
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()