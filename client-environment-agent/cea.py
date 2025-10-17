"""
Shunyata Client Environment Agent (CEA)
"""
import argparse
import json
import threading
import uuid
import time
from flask import Flask, render_template, request, jsonify
import requests

try:
    from executor import run_code_and_update_status
except ImportError:
    print("Warning: executor.py not found. Local testing will not work.")
    run_code_and_update_status = None

app = Flask(__name__, template_folder="templates")

# MODIFICATION: Replaced CJS_IP and CJS_PORT with a single CJS_URL
CJS_URL = None
JOB_STATUSES: dict = {}

# MODIFICATION: Simplified function to return the full URL
def get_cjs_url():
    return CJS_URL

def log(message, level="INFO"):
    print(f"[{time.strftime('%H:%M:%S')}] [{level}] {message}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/problems", methods=["GET"])
def get_problems():
    log("GET /problems - Fetching problems from CJS")
    if not CJS_URL: return jsonify({"error": "CJS URL not configured"}), 400
    try:
        # Use the full URL directly
        response = requests.get(f"{get_cjs_url()}/api/problems", timeout=5)
        response.raise_for_status()
        return jsonify(response.json()), 200
    except requests.exceptions.RequestException as e:
        error_msg = f"Cannot reach Central Judge Server. Details: {e}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 503

@app.route("/submit", methods=["POST"])
def submit_code():
    log("POST /submit - Submitting code to CJS")
    if not CJS_URL: return jsonify({"error": "CJS URL not configured"}), 400
    try:
        submission = request.get_json()
        # Use the full URL directly
        response = requests.post(f"{get_cjs_url()}/api/submit", json=submission, timeout=15)
        response.raise_for_status()
        return jsonify(response.json()), 200
    except requests.exceptions.RequestException as e:
        error_msg = f"Cannot reach Central Judge Server. Details: {e}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 503

@app.route("/scoreboard", methods=["GET"])
def get_scoreboard():
    if not CJS_URL: return jsonify({"error": "CJS URL not configured"}), 400
    try:
        # Use the full URL directly
        response = requests.get(f"{get_cjs_url()}/api/scoreboard", timeout=5)
        response.raise_for_status()
        return jsonify(response.json()), 200
    except requests.exceptions.RequestException as e:
        error_msg = f"Cannot reach Central Judge Server. Details: {e}"
        log(error_msg, "ERROR")
        return jsonify({"error": error_msg}), 503

@app.route("/run-async", methods=["POST"])
def run_async_tests():
    if not run_code_and_update_status:
        return jsonify({"error": "Executor not available"}), 503
    data = request.get_json()
    job_id = str(uuid.uuid4())
    JOB_STATUSES[job_id] = {"status": "queued", "progress": 0}
    
    thread = threading.Thread(
        target=run_code_and_update_status,
        args=(job_id, data["code"], data["problem_id"], data["language"], JOB_STATUSES),
        daemon=True
    )
    thread.start()
    return jsonify({"job_id": job_id}), 202

@app.route("/job-status/<job_id>", methods=["GET"])
def get_job_status(job_id):
    status = JOB_STATUSES.get(job_id)
    if not status:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(status), 200

def main():
    # MODIFICATION: Changed global variable
    global CJS_URL
    parser = argparse.ArgumentParser(description="Shunyata Client Environment Agent")
    
    # MODIFICATION: Changed command-line arguments
    parser.add_argument("--server-url", required=True, help="Full URL of the Central Judge Server (e.g., from ngrok)")
    parser.add_argument("--port", type=int, default=8000, help="Local port for this agent")
    args = parser.parse_args()
    
    # MODIFICATION: Assign the new URL argument
    CJS_URL = args.server_url
    
    log("=" * 50)
    log("🚀 Shunyata Client Environment Agent starting...")
    log(f"Connecting to Central Judge Server at: {get_cjs_url()}")
    log(f"Open your browser to http://127.0.0.1:{args.port}")
    log("=" * 50)
    
    app.run(host="127.0.0.1", port=args.port, debug=False)

if __name__ == "__main__":
    main()