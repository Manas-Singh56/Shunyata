"""
Shunyata Client Environment Agent (CEA)
Main controller for the participant-side client.

Runs a local Flask web server on http://localhost:8000 to serve the contest UI.
Communicates with the Central Judge Server (CJS) over LAN for problem fetching and code submission.
Integrates local code execution via executor.py and optional network lockdown via lockdown.py.

Enhanced Features:
- Asynchronous code execution with real-time status updates
- Background job processing for non-blocking UI
- WebSocket-like polling for live progress tracking
- Thread-safe execution management
- Improved error handling and recovery
"""

import argparse
import json
import os
import sys
import threading
import uuid
import time
from pathlib import Path
from typing import Dict, Any

from flask import Flask, render_template, request, jsonify
import requests

# Import local modules (executor and lockdown)
try:
    from executor import run_code_locally, run_code_and_update_status
    EXECUTOR_AVAILABLE = True
except ImportError:
    print("Warning: executor.py not found. Local testing will not work.")
    run_code_locally = None
    run_code_and_update_status = None
    EXECUTOR_AVAILABLE = False

try:
    import lockdown
    LOCKDOWN_AVAILABLE = True
except ImportError:
    print("Warning: lockdown.py not found. Lockdown features disabled.")
    lockdown = None
    LOCKDOWN_AVAILABLE = False


# Flask app setup
app = Flask(__name__, template_folder="templates")

# Global variables
CJS_IP = None  # Central Judge Server IP (passed via command line)
CJS_PORT = 5000  # Default CJS port
LOCKDOWN_ACTIVE = False  # Track lockdown state

# Job tracking for asynchronous execution
JOB_STATUSES: Dict[str, Dict[str, Any]] = {}
JOB_CLEANUP_LOCK = threading.Lock()
MAX_JOB_HISTORY = 100  # Maximum number of completed jobs to keep in memory


def get_cjs_url():
    """Construct the base URL for the CJS."""
    if not CJS_IP:
        return None
    return f"http://{CJS_IP}:{CJS_PORT}"


def log(message, level="INFO"):
    """Simple console logging with timestamp."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def cleanup_old_jobs():
    """Remove old completed jobs to prevent memory bloat."""
    with JOB_CLEANUP_LOCK:
        if len(JOB_STATUSES) > MAX_JOB_HISTORY:
            # Remove oldest completed jobs
            completed_jobs = [
                (job_id, data) for job_id, data in JOB_STATUSES.items()
                if data.get("progress", 0) >= 100
            ]
            
            if len(completed_jobs) > MAX_JOB_HISTORY // 2:
                # Sort by completion time (if available) or just take oldest
                completed_jobs.sort(key=lambda x: x[1].get("completed_at", 0))
                
                # Remove oldest half
                to_remove = len(completed_jobs) - (MAX_JOB_HISTORY // 2)
                for job_id, _ in completed_jobs[:to_remove]:
                    del JOB_STATUSES[job_id]
                    log(f"Cleaned up old job: {job_id}", "DEBUG")


# ============================================================================
# ROUTES - BASIC PAGES
# ============================================================================

@app.route("/")
def index():
    """Serve the main participant UI (index.html)."""
    log(f"GET / - Serving main page")
    return render_template("index.html")


@app.route("/status", methods=["GET"])
def get_agent_status():
    """
    Return current agent status (health check).
    Useful for debugging and verifying agent is running.
    """
    lockdown_status = None
    if LOCKDOWN_AVAILABLE:
        lockdown_status = lockdown.get_lockdown_status()
    
    status = {
        "agent_running": True,
        "cjs_ip": CJS_IP,
        "cjs_url": get_cjs_url(),
        "lockdown_active": LOCKDOWN_ACTIVE,
        "lockdown_status": lockdown_status,
        "executor_available": EXECUTOR_AVAILABLE,
        "lockdown_available": LOCKDOWN_AVAILABLE,
        "active_jobs": len([j for j in JOB_STATUSES.values() if j.get("progress", 100) < 100]),
        "total_jobs": len(JOB_STATUSES)
    }
    return jsonify(status), 200


# ============================================================================
# ROUTES - CJS COMMUNICATION
# ============================================================================

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
        language = data.get("language", "cpp")
        
        if not source_code or not problem_id:
            return jsonify({"error": "Missing code or problem_id"}), 400
        
        log(f"Submitting code for problem {problem_id} from {participant_name}")
        
        # Prepare submission payload
        submission = {
            "code": source_code,
            "problem_id": problem_id,
            "participant_name": participant_name,
            "language": language
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


# ============================================================================
# ROUTES - LOCAL CODE EXECUTION (SYNCHRONOUS - LEGACY)
# ============================================================================

@app.route("/run-local", methods=["POST"])
def run_local_tests():
    """
    [LEGACY] Accept code snippet + problem ID, run locally against sample test cases.
    Returns test results to the participant for instant feedback.
    
    Note: This is the synchronous version. For better UX, use /run-async instead.
    """
    log("POST /run-local - Running local tests (synchronous)")
    
    if not run_code_locally:
        return jsonify({"error": "Local executor not available"}), 503
    
    try:
        data = request.get_json()
        source_code = data.get("code", "")
        problem_id = data.get("problem_id", "")
        language = data.get("language", "cpp")
        
        if not source_code or not problem_id:
            return jsonify({"error": "Missing code or problem_id"}), 400
        
        log(f"Running local tests for problem {problem_id} ({language})")
        
        # Call executor to run code locally (blocks until complete)
        result = run_code_locally(source_code, problem_id, language)
        
        log(f"Local test completed for problem {problem_id}: {result.get('status', 'unknown')}")
        return jsonify(result), 200
        
    except Exception as e:
        error_msg = f"Error running local tests: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


# ============================================================================
# ROUTES - ASYNCHRONOUS CODE EXECUTION (NEW)
# ============================================================================

@app.route("/run-async", methods=["POST"])
def run_async_tests():
    """
    [NEW] Start asynchronous code execution with real-time status updates.
    Returns a job_id immediately, allowing the UI to poll for progress.
    
    Request body:
        {
            "code": "...",
            "problem_id": "P1",
            "language": "cpp"  // or "python"
        }
    
    Response:
        {
            "job_id": "uuid-string",
            "status": "queued",
            "message": "Execution job queued successfully"
        }
    """
    log("POST /run-async - Starting asynchronous execution")
    
    if not run_code_and_update_status:
        return jsonify({"error": "Async executor not available"}), 503
    
    try:
        data = request.get_json()
        source_code = data.get("code", "")
        problem_id = data.get("problem_id", "")
        language = data.get("language", "cpp")
        
        if not source_code or not problem_id:
            return jsonify({"error": "Missing code or problem_id"}), 400
        
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # Initialize job status
        JOB_STATUSES[job_id] = {
            "status": "queued",
            "output": "",
            "progress": 0,
            "problem_id": problem_id,
            "language": language,
            "created_at": time.time()
        }
        
        log(f"Created job {job_id} for problem {problem_id} ({language})")
        
        # Start execution in background thread
        thread = threading.Thread(
            target=run_code_and_update_status,
            args=(job_id, source_code, problem_id, language, JOB_STATUSES),
            daemon=True
        )
        thread.start()
        
        # Cleanup old jobs in background
        cleanup_thread = threading.Thread(target=cleanup_old_jobs, daemon=True)
        cleanup_thread.start()
        
        return jsonify({
            "job_id": job_id,
            "status": "queued",
            "message": "Execution job queued successfully"
        }), 202  # 202 Accepted - request accepted for processing
        
    except Exception as e:
        error_msg = f"Error starting async execution: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


@app.route("/job-status/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """
    Poll endpoint for checking execution status.
    The UI can call this repeatedly to get live updates.
    
    Response:
        {
            "status": "running",
            "output": "...",
            "progress": 75,
            "execution_time": "1.23s",
            ...
        }
    """
    if job_id not in JOB_STATUSES:
        return jsonify({
            "status": "not_found",
            "error": f"Job {job_id} not found or expired"
        }), 404
    
    status = JOB_STATUSES[job_id]
    
    # Mark job as completed if at 100%
    if status.get("progress", 0) >= 100 and "completed_at" not in status:
        status["completed_at"] = time.time()
    
    return jsonify(status), 200


@app.route("/job-cancel/<job_id>", methods=["POST"])
def cancel_job(job_id):
    """
    Cancel a running execution job.
    Note: Due to subprocess limitations, this may not stop the execution immediately.
    """
    if job_id not in JOB_STATUSES:
        return jsonify({"error": "Job not found"}), 404
    
    status = JOB_STATUSES[job_id]
    
    if status.get("progress", 0) >= 100:
        return jsonify({"message": "Job already completed"}), 200
    
    # Mark as cancelled
    status["status"] = "cancelled"
    status["output"] = "Execution cancelled by user"
    status["progress"] = 100
    status["completed_at"] = time.time()
    
    log(f"Job {job_id} cancelled by user")
    return jsonify({"message": "Job cancelled"}), 200


@app.route("/jobs", methods=["GET"])
def list_jobs():
    """
    List all jobs (useful for debugging).
    Optional query params:
        - limit: max number of jobs to return (default: 20)
        - status: filter by status (running, completed, error, etc.)
    """
    limit = request.args.get("limit", 20, type=int)
    status_filter = request.args.get("status", None)
    
    jobs = []
    for job_id, data in list(JOB_STATUSES.items())[:limit]:
        if status_filter and data.get("status") != status_filter:
            continue
        
        jobs.append({
            "job_id": job_id,
            "status": data.get("status"),
            "progress": data.get("progress", 0),
            "problem_id": data.get("problem_id"),
            "created_at": data.get("created_at"),
            "completed_at": data.get("completed_at")
        })
    
    return jsonify({
        "total": len(JOB_STATUSES),
        "returned": len(jobs),
        "jobs": jobs
    }), 200


# ============================================================================
# ROUTES - NETWORK LOCKDOWN
# ============================================================================

@app.route("/lockdown", methods=["POST"])
def toggle_lockdown():
    """
    Enable or disable network lockdown mode.
    Lockdown mode blocks internet access except to localhost (and optionally CJS).
    Requires admin privileges on Windows or root on Unix.
    
    Request body:
        {
            "action": "enable" | "disable"
        }
    """
    global LOCKDOWN_ACTIVE
    
    log("POST /lockdown - Toggling lockdown mode")
    
    if not LOCKDOWN_AVAILABLE:
        return jsonify({"error": "Lockdown module not available"}), 503
    
    try:
        data = request.get_json()
        action = data.get("action", "").lower()  # "enable" or "disable"
        
        if action == "enable":
            if LOCKDOWN_ACTIVE:
                return jsonify({
                    "message": "Lockdown already active",
                    "status": lockdown.get_lockdown_status()
                }), 200
            
            log("Activating network lockdown")
            success = lockdown.enable(cjs_ip=CJS_IP)
            LOCKDOWN_ACTIVE = success
            
            return jsonify({
                "message": "Lockdown enabled" if success else "Lockdown enabled (demo mode)",
                "status": lockdown.get_lockdown_status()
            }), 200
            
        elif action == "disable":
            if not LOCKDOWN_ACTIVE:
                return jsonify({
                    "message": "Lockdown not active",
                    "status": lockdown.get_lockdown_status()
                }), 200
            
            log("Disabling network lockdown")
            success = lockdown.release()
            LOCKDOWN_ACTIVE = False
            
            return jsonify({
                "message": "Lockdown disabled",
                "status": lockdown.get_lockdown_status()
            }), 200
            
        else:
            return jsonify({"error": "Invalid action (use 'enable' or 'disable')"}), 400
            
    except PermissionError:
        error_msg = "Admin privileges required for lockdown. Run as Administrator/root."
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 403
    except Exception as e:
        error_msg = f"Error toggling lockdown: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


@app.route("/lockdown-status", methods=["GET"])
def get_lockdown_status():
    """
    Get detailed lockdown status information.
    """
    if not LOCKDOWN_AVAILABLE:
        return jsonify({
            "available": False,
            "error": "Lockdown module not loaded"
        }), 200
    
    status = lockdown.get_lockdown_status()
    status["available"] = True
    return jsonify(status), 200


@app.route("/lockdown-emergency", methods=["POST"])
def emergency_lockdown_cleanup():
    """
    Emergency endpoint to forcefully remove all lockdown rules.
    Use if rules get stuck after abnormal termination.
    Requires admin privileges.
    """
    if not LOCKDOWN_AVAILABLE:
        return jsonify({"error": "Lockdown module not available"}), 503
    
    try:
        log("Emergency lockdown cleanup requested", "WARN")
        lockdown.emergency_cleanup()
        
        global LOCKDOWN_ACTIVE
        LOCKDOWN_ACTIVE = False
        
        return jsonify({
            "message": "Emergency cleanup completed",
            "status": lockdown.get_lockdown_status()
        }), 200
        
    except Exception as e:
        error_msg = f"Error during emergency cleanup: {str(e)}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 500


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    """Handle 500 errors."""
    log(f"Internal server error: {str(e)}", "ERROR")
    return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Parse command-line arguments and start the Flask server."""
    global CJS_IP, CJS_PORT
    
    parser = argparse.ArgumentParser(
        description="Shunyata Client Environment Agent - Local contest client with async execution"
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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode (not recommended for contests)"
    )
    
    args = parser.parse_args()
    
    CJS_IP = args.server_ip
    CJS_PORT = args.server_port
    
    log("=" * 70)
    log("Shunyata Client Environment Agent starting...")
    log(f"Central Judge Server: {get_cjs_url()}")
    log(f"Local server: http://127.0.0.1:{args.port}")
    log(f"Executor available: {EXECUTOR_AVAILABLE}")
    log(f"Lockdown available: {LOCKDOWN_AVAILABLE}")
    log("")
    log("Open browser to http://localhost:{args.port}")
    log("=" * 70)
    log("")
    
    # Start Flask app
    app.run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()