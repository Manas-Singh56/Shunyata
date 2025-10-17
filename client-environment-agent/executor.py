"""
executor.py - Asynchronous Local Code Execution Engine for Shunyata (Corrected)
"""
import json
import subprocess
import time
import shutil
from pathlib import Path
import requests # <-- Add this import

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not found for memory limits. Install with: pip install psutil")

try:
    from lockdown import lockdown_context
    LOCKDOWN_AVAILABLE = True
except ImportError:
    LOCKDOWN_AVAILABLE = False
    print("Warning: lockdown.py not available. Code will run without network restrictions.")
    from contextlib import contextmanager
    @contextmanager
    def lockdown_context():
        yield

DEFAULT_TIME_LIMIT_S = 3
DEFAULT_MEMORY_LIMIT_MB = 256

# --- MODIFICATION START ---
# This function now fetches problem data via an HTTP request to the local CEA
def load_problem_data(problem_id: str) -> dict:
    """Fetches all problems from the local CEA and returns data for the specific problem_id."""
    # The CEA runs on localhost port 8000 by default
    cea_problems_url = "http://127.0.0.1:8000/problems"
    try:
        response = requests.get(cea_problems_url, timeout=5)
        response.raise_for_status()
        all_problems = response.json()
        return all_problems.get(problem_id)
    except requests.exceptions.RequestException as e:
        print(f"[Executor Error] Could not fetch problem data from CEA: {e}")
        return None
# --- MODIFICATION END ---


def run_code_and_update_status(job_id, source_code, problem_id, language, status_store):
    def update_status(status, output="", progress=0, **kwargs):
        status_store[job_id].update({"status": status, "output": output, "progress": progress, **kwargs})
    
    exec_folder = Path(f"./temp_exec/run_{job_id}")
    exec_folder.mkdir(parents=True, exist_ok=True)
    
    try:
        update_status("Loading Problem", progress=10)
        # Use the new, corrected function
        problem_data = load_problem_data(problem_id)
        if not problem_data:
            update_status("Error", f"Problem '{problem_id}' not found or CEA is unreachable.", 100)
            return
        
        time_limit = problem_data.get("time_limit", DEFAULT_TIME_LIMIT_S)
        mem_limit = problem_data.get("memory_limit", DEFAULT_MEMORY_LIMIT_MB)
        
        if not problem_data.get("sample_test_cases"):
             update_status("Error", f"No sample test cases found for problem '{problem_id}'.", 100)
             return
        sample_case = problem_data["sample_test_cases"][0]
        
        if language.lower() == "cpp":
            exec_result = execute_cpp(source_code, sample_case, exec_folder, time_limit, mem_limit, update_status)
        elif language.lower() == "python":
            exec_result = execute_python(source_code, sample_case, exec_folder, time_limit, mem_limit, update_status)
        else:
            exec_result = {"status": "error", "output": f"Unsupported language: {language}"}
        
        update_status(progress=100, **exec_result, expected=sample_case["output"])
    
    except Exception as e:
        update_status("System Error", f"Executor failed: {e}", 100)
    finally:
        shutil.rmtree(exec_folder, ignore_errors=True)


def execute_cpp(source_code, test_case, exec_folder, time_limit, mem_limit, update_status):
    update_status("Compiling", progress=30)
    source_file = exec_folder / "main.cpp"
    source_file.write_text(source_code)
    executable = exec_folder / "main"
    compile_cmd = ["g++", "-std=c++17", str(source_file), "-o", str(executable)]
    
    try:
        compile_proc = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=10)
        if compile_proc.returncode != 0:
            return {"status": "compilation_error", "output": compile_proc.stderr}
    except FileNotFoundError:
        return {"status": "compilation_error", "output": "g++ compiler not found. Please install GCC."}
    
    update_status("Running", progress=60)
    return _run_and_verify([str(executable)], test_case, exec_folder, time_limit, mem_limit)

def execute_python(source_code, test_case, exec_folder, time_limit, mem_limit, update_status):
    update_status("Preparing", progress=30)
    source_file = exec_folder / "main.py"
    source_file.write_text(source_code)
    update_status("Running", progress=60)
    return _run_and_verify(["python", str(source_file)], test_case, exec_folder, time_limit, mem_limit)

def _run_and_verify(command, test_case, exec_folder, time_limit, mem_limit_mb):
    result = {"status": "unknown", "output": "", "memory_usage": "0 MB"}
    start_time = time.time()

    with lockdown_context():
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            p = psutil.Process(process.pid) if PSUTIL_AVAILABLE else None
            max_memory = 0

            while process.poll() is None:
                if time.time() - start_time > time_limit:
                    process.kill()
                    raise subprocess.TimeoutExpired(command, time_limit)
                if p:
                    try:
                        mem_info = p.memory_info().rss
                        max_memory = max(max_memory, mem_info)
                        if mem_info > mem_limit_mb * 1024 * 1024:
                            process.kill()
                            result["status"] = "memory_limit_exceeded"
                            break
                    except psutil.NoSuchProcess:
                        break # Process finished between checks
                time.sleep(0.01)

            stdout, stderr = process.communicate()
            if PSUTIL_AVAILABLE:
                result["memory_usage"] = f"{max_memory / 1024 / 1024:.2f} MB"

            if result["status"] != "memory_limit_exceeded":
                if process.returncode != 0:
                    result["status"], result["output"] = "runtime_error", stderr
                elif normalize_output(stdout) == normalize_output(test_case["output"]):
                    result["status"], result["output"] = "success", stdout
                else:
                    result["status"], result["output"] = "wrong_answer", stdout
        
        except subprocess.TimeoutExpired:
            result["status"] = "time_limit_exceeded"
        except Exception as e:
            result["status"], result["output"] = "error", str(e)
    
    result["execution_time"] = f"{time.time() - start_time:.2f}s"
    return result

def normalize_output(output: str) -> str:
    return output.strip().replace('\r\n', '\n')