"""
executor.py - Local Code Execution Engine for Shunyata
Part of the Client Environment Agent (CEA)

Handles compilation and execution of C++ and Python code locally
for instant feedback.

Features:
- Time and Memory Limit Enforcement
- Network Isolation via lockdown.py
- Centralized configuration via problems.json
"""

import os
import json
import subprocess
import time
import shutil
from pathlib import Path

# psutil is required for memory limit enforcement
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not found. Memory limits will not be enforced.")
    print("         Install with: pip install psutil")

# Import lockdown module for network security
try:
    import lockdown
    LOCKDOWN_AVAILABLE = True
except ImportError:
    LOCKDOWN_AVAILABLE = False
    print("Warning: lockdown.py not available. Code will run without network restrictions.")

# Default limits if not specified in problem data
DEFAULT_TIME_LIMIT_S = 3
DEFAULT_MEMORY_LIMIT_MB = 256


def run_code_locally(source_code: str, problem_id: str, language: str = "cpp") -> dict:
    """
    Compile and execute code locally, comparing output with the first sample test case.
    
    Args:
        source_code: The user's code as a string.
        problem_id: Problem identifier (e.g., "P1").
        language: Programming language - "cpp" or "python".
    
    Returns:
        dict: Execution result with status, output, expected output, and execution time.
    """
    start_time = time.time()
    
    result = {
        "status": "unknown", "output": "", "expected": "",
        "execution_time": "0.00s", "memory_usage": "0 MB"
    }
    
    # Create a unique temporary directory for this execution
    exec_folder = Path(f"./temp_exec/run_{int(time.time() * 1000)}")
    exec_folder.mkdir(parents=True, exist_ok=True)
    
    try:
        # Load problem data, which includes limits and test cases
        problem_data = load_problem_data(problem_id)
        if not problem_data:
            result["status"] = "error"
            result["output"] = f"Problem {problem_id} not found or invalid."
            return result
            
        # Extract limits and the first sample test case
        time_limit = problem_data.get("time_limit", DEFAULT_TIME_LIMIT_S)
        mem_limit = problem_data.get("memory_limit", DEFAULT_MEMORY_LIMIT_MB)
        sample_case = problem_data["sample_test_cases"][0]
        result["expected"] = sample_case["output"]
        
        # Execute based on language
        if language.lower() == "cpp":
            exec_result = execute_cpp(source_code, sample_case, exec_folder, time_limit, mem_limit)
        elif language.lower() == "python":
            exec_result = execute_python(source_code, sample_case, exec_folder, time_limit, mem_limit)
        else:
            result["status"] = "error"
            result["output"] = f"Unsupported language: {language}"
            return result
        
        result.update(exec_result)
        
    except Exception as e:
        result["status"] = "error"
        result["output"] = f"An unexpected error occurred in the executor: {str(e)}"
    
    finally:
        elapsed = time.time() - start_time
        result["execution_time"] = f"{elapsed:.2f}s"
        cleanup_temp_files(exec_folder)
        
    return result


def load_problem_data(problem_id: str) -> dict:
    """
    Load problem data (limits, test cases) from problems.json.
    Uses a path relative to this script's location for reliability.
    """
    script_dir = Path(__file__).parent
    problems_path = script_dir.parent / "central-judge-server" / "contest_data" / "problems.json"
    
    if not problems_path.exists():
        # Fallback for testing from root directory
        problems_path = Path("./central-judge-server/contest_data/problems.json")

    if problems_path.exists():
        with open(problems_path, 'r') as f:
            problems = json.load(f)
            problem_data = problems.get(problem_id)
            # Basic validation
            if problem_data and "sample_test_cases" in problem_data and problem_data["sample_test_cases"]:
                return problem_data
    return None


def _run_and_verify(command: list, test_case: dict, exec_folder: Path, time_limit: float, mem_limit_mb: int) -> dict:
    """
    Helper function to run a program, enforce limits, and verify output.
    """
    result = {"status": "unknown", "output": "", "memory_usage": "0 MB"}
    input_data = test_case["input"]
    
    lockdown_enabled = False
    try:
        if LOCKDOWN_AVAILABLE:
            lockdown.enable()
            lockdown_enabled = True

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(exec_folder)
        )
        
        if PSUTIL_AVAILABLE:
            p = psutil.Process(process.pid)
            max_memory = 0
            # Monitor memory usage in a tight loop while the process is running
            while process.poll() is None:
                try:
                    mem_info = p.memory_info().rss
                    if mem_info > max_memory:
                        max_memory = mem_info
                    if mem_info > mem_limit_mb * 1024 * 1024:
                        p.kill()
                        result["status"] = "memory_limit_exceeded"
                        result["output"] = f"Memory usage exceeded {mem_limit_mb} MB"
                        result["memory_usage"] = f"{max_memory / 1024 / 1024:.2f} MB"
                        return result
                except psutil.NoSuchProcess:
                    break # Process finished
                time.sleep(0.01) # Poll interval
            result["memory_usage"] = f"{max_memory / 1024 / 1024:.2f} MB"

        # Communicate with the process to get output and enforce time limit
        stdout, stderr = process.communicate(input=input_data, timeout=time_limit)
        
        if process.returncode != 0:
            result["status"] = "runtime_error"
            result["output"] = stderr if stderr else f"Program exited with non-zero code: {process.returncode}"
        else:
            if normalize_output(stdout) == normalize_output(test_case["output"]):
                result["status"] = "success"
                result["output"] = stdout
            else:
                result["status"] = "wrong_answer"
                result["output"] = stdout

    except subprocess.TimeoutExpired:
        process.kill()
        result["status"] = "time_limit_exceeded"
        result["output"] = f"Execution time exceeded {time_limit} seconds"
    except FileNotFoundError:
        result["status"] = "runtime_error"
        result["output"] = f"Command not found: '{command[0]}'. Is it in your PATH?"
    except Exception as e:
        result["status"] = "runtime_error"
        result["output"] = f"An unexpected execution error occurred: {str(e)}"
    finally:
        if lockdown_enabled:
            lockdown.release()
            
    return result


def execute_cpp(source_code: str, test_case: dict, exec_folder: Path, time_limit: float, mem_limit_mb: int) -> dict:
    """Compile and execute C++ code."""
    source_file = exec_folder / "main.cpp"
    source_file.write_text(source_code)
    
    executable = exec_folder / "main.exe" if os.name == 'nt' else exec_folder / "main"
    compile_cmd = ["g++", str(source_file), "-o", str(executable)]
    
    try:
        compile_proc = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=10)
        if compile_proc.returncode != 0:
            return {"status": "compilation_error", "output": compile_proc.stderr}
    except FileNotFoundError:
        return {"status": "compilation_error", "output": "g++ compiler not found. Please install GCC."}
    except subprocess.TimeoutExpired:
        return {"status": "compilation_error", "output": "Compilation timed out (>10s)."}
        
    return _run_and_verify([str(executable)], test_case, exec_folder, time_limit, mem_limit_mb)


def execute_python(source_code: str, test_case: dict, exec_folder: Path, time_limit: float, mem_limit_mb: int) -> dict:
    """Execute Python code."""
    source_file = exec_folder / "main.py"
    source_file.write_text(source_code)
    
    return _run_and_verify(["python", str(source_file)], test_case, exec_folder, time_limit, mem_limit_mb)


def normalize_output(output: str) -> str:
    """Normalize output for comparison (strip whitespace, normalize line endings)."""
    return output.strip().replace('\r\n', '\n')


def cleanup_temp_files(exec_folder: Path):
    """Remove temporary execution files."""
    if exec_folder.exists():
        shutil.rmtree(exec_folder, ignore_errors=True)

# Example usage for self-contained testing
if __name__ == "__main__":
    # --- Create dummy contest data for testing ---
    dummy_problems_data = {
        "P1": {
            "time_limit": 2.0,
            "memory_limit": 128,
            "sample_test_cases": [
                {
                    "input": "3 5",
                    "output": "8"
                }
            ]
        }
    }
    # Create the necessary directory structure for the test
    dummy_data_dir = Path("./central-judge-server/contest_data")
    dummy_data_dir.mkdir(parents=True, exist_ok=True)
    with open(dummy_data_dir / "problems.json", "w") as f:
        json.dump(dummy_problems_data, f, indent=2)
    
    # --- Test with Python code ---
    test_python_code = "a, b = map(int, input().split())\nprint(a + b)"
    py_result = run_code_locally(test_python_code, problem_id="P1", language="python")
    print("--- Python Test Result ---")
    print(json.dumps(py_result, indent=2))
    
    # --- Test with C++ code ---
    test_cpp_code = """
#include <iostream>
int main() {
    int a, b;
    std::cin >> a >> b;
    std::cout << a + b << std::endl;
    return 0;
}"""
    cpp_result = run_code_locally(test_cpp_code, problem_id="P1", language="cpp")
    print("\n--- C++ Test Result ---")
    print(json.dumps(cpp_result, indent=2))

    # --- Cleanup dummy files ---
    shutil.rmtree("./central-judge-server", ignore_errors=True)
    shutil.rmtree("./temp_exec", ignore_errors=True)