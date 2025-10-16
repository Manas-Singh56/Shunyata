# """
# Shunyata Central Judge (judge.py)
# Handles the compilation, execution, and verification of code submissions.
# """
# import json
# import os
# import shutil
# import subprocess
# import time
# from pathlib import Path
# from typing import Dict, Any, List

# try:
#     import psutil
#     PSUTIL_AVAILABLE = True
# except ImportError:
#     PSUTIL_AVAILABLE = False
#     print("Warning: psutil not found. Memory limits will not be enforced.")

# CONTEST_DATA_DIR = Path("./contest_data")
# SUBMISSIONS_DIR = Path("./submissions")
# PROBLEMS_FILE = CONTEST_DATA_DIR / "problems.json"
# SCOREBOARD_FILE = CONTEST_DATA_DIR / "scoreboard.json"

# CONTEST_DATA_DIR.mkdir(exist_ok=True)
# SUBMISSIONS_DIR.mkdir(exist_ok=True)

# def load_problems() -> Dict[str, Any]:
#     if not PROBLEMS_FILE.exists():
#         return {}
#     with open(PROBLEMS_FILE, 'r') as f:
#         # Handle empty problems.json
#         try:
#             return json.load(f)
#         except json.JSONDecodeError:
#             return {}

# def update_scoreboard(participant: str, problem_id: str, verdict: str):
#     if verdict != "Accepted":
#         return
#     try:
#         scoreboard = {}
#         if SCOREBOARD_FILE.exists() and os.path.getsize(SCOREBOARD_FILE) > 0:
#             with open(SCOREBOARD_FILE, 'r') as f:
#                 scoreboard = json.load(f)
        
#         if participant not in scoreboard:
#             scoreboard[participant] = {"score": 0, "problems_solved": {}}
#         if problem_id not in scoreboard[participant]["problems_solved"]:
#             scoreboard[participant]["problems_solved"][problem_id] = {"verdict": "Accepted", "timestamp": time.time()}
#             scoreboard[participant]["score"] += 100
        
#         with open(SCOREBOARD_FILE, 'w') as f:
#             json.dump(scoreboard, f, indent=4)
#     except (IOError, json.JSONDecodeError) as e:
#         print(f"Error updating scoreboard: {e}")

# def _compile_cpp(source_code: str, exec_dir: Path) -> (Path, str):
#     source_file = exec_dir / "main.cpp"
#     source_file.write_text(source_code)
#     executable = exec_dir / "main.exe" if os.name == 'nt' else exec_dir / "main"
#     compile_cmd = ["g++", "-std=c++17", "-O2", "-static", str(source_file), "-o", str(executable)]
#     try:
#         proc = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=10)
#         if proc.returncode != 0:
#             return None, proc.stderr
#         return executable, None
#     except FileNotFoundError:
#         return None, "g++ compiler not found."
#     except subprocess.TimeoutExpired:
#         return None, "Compilation timed out."

# def _run_with_limits(command: list, input_data: str, cwd: Path, time_limit: float, mem_limit_mb: int) -> Dict[str, Any]:
#     try:
#         process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
#         p = psutil.Process(process.pid) if PSUTIL_AVAILABLE else None
#         if p:
#             mem_limit_bytes = mem_limit_mb * 1024 * 1024
#             while process.poll() is None:
#                 try:
#                     if p.memory_info().rss > mem_limit_bytes:
#                         p.kill()
#                         return {"verdict": "Memory Limit Exceeded"}
#                     time.sleep(0.01)
#                 except psutil.NoSuchProcess:
#                     break
#         stdout, stderr = process.communicate(input=input_data, timeout=time_limit)
#         if process.returncode != 0:
#             return {"verdict": "Runtime Error", "details": stderr}
#         return {"verdict": "Passed", "output": stdout}
#     except subprocess.TimeoutExpired:
#         process.kill()
#         return {"verdict": "Time Limit Exceeded"}
#     except Exception as e:
#         return {"verdict": "System Error", "details": str(e)}

# def _normalize_output(text: str) -> str:
#     return text.strip().replace('\r\n', '\n')

# def run_test_cases(submission_data: Dict[str, Any], test_cases: List[Dict[str, str]], problem_info: Dict[str, Any]) -> Dict[str, Any]:
#     run_id = f"{submission_data['participant_name']}_{submission_data['problem_id']}_{int(time.time() * 1000)}"
#     exec_dir = SUBMISSIONS_DIR / run_id
#     exec_dir.mkdir(parents=True, exist_ok=True)
#     try:
#         if submission_data["language"] == "cpp":
#             executable_path, compile_error = _compile_cpp(submission_data["code"], exec_dir)
#             if compile_error:
#                 return {"verdict": "Compilation Error", "details": compile_error}
#             run_command = [str(executable_path)]
#         elif submission_data["language"] == "python":
#             script_path = exec_dir / "main.py"
#             script_path.write_text(submission_data["code"])
#             # --- FIX: Use a relative path, relying on the 'cwd' parameter ---
#             run_command = ["python", "main.py"]
#         else:
#             return {"verdict": "System Error", "details": "Unsupported language"}
        
#         for i, test_case in enumerate(test_cases):
#             run_result = _run_with_limits(run_command, test_case["input"], exec_dir, problem_info["time_limit"], problem_info["memory_limit"])
#             if run_result["verdict"] != "Passed":
#                 run_result["details"] = f"Failed on test case #{i + 1}. {run_result.get('details', '')}"
#                 return run_result
#             if "output" not in test_case: # Handle cases with no expected output
#                 test_case["output"] = ""
#             if _normalize_output(run_result["output"]) != _normalize_output(test_case["output"]):
#                 return {"verdict": "Wrong Answer", "details": f"Failed on test case #{i + 1}"}
#         return {"verdict": "Accepted"}
#     finally:
#         shutil.rmtree(exec_dir, ignore_errors=True)

# def judge_and_verify(submission_data: Dict[str, Any]) -> Dict[str, Any]:
#     problem_id = submission_data["problem_id"]
#     problems = load_problems()
#     problem_info = problems.get(problem_id)
#     if not problem_info:
#         return {"verdict": "System Error", "details": "Problem not found."}

#     # Use sample cases + hidden cases (if they exist)
#     sample_cases = problem_info.get("sample_test_cases", [])
#     hidden_cases = problem_info.get("hidden_test_cases", [])
#     all_cases = sample_cases + hidden_cases
    
#     if not all_cases:
#         return {"verdict": "System Error", "details": "No test cases found for this problem."}

#     final_result = run_test_cases(submission_data, all_cases, problem_info)

#     if final_result["verdict"] == "Accepted":
#         update_scoreboard(submission_data["participant_name"], problem_id, "Accepted")
#         final_result["details"] = "All sample and hidden test cases passed."
    
#     return final_result
import json, os, shutil, subprocess, time
from pathlib import Path
from difflib import SequenceMatcher

# === CONFIG ===
CONTEST_DATA_DIR = Path("./contest_data")
SUBMISSIONS_DIR = Path("./submissions")
PROBLEMS_FILE = CONTEST_DATA_DIR / "problems.json"
SCOREBOARD_FILE = CONTEST_DATA_DIR / "scoreboard.json"
SIMILARITY_THRESHOLD = 0.90  # 90%

CONTEST_DATA_DIR.mkdir(exist_ok=True)
SUBMISSIONS_DIR.mkdir(exist_ok=True)


def load_json(path):
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}


def save_json_atomic(path, data):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)


def _compile_cpp(code, dir_):
    src = dir_ / "main.cpp"
    src.write_text(code)
    exe = dir_ / ("main.exe" if os.name == "nt" else "main")
    proc = subprocess.run(["g++", "-std=c++17", "-O2", str(src), "-o", str(exe)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None, proc.stderr
    return exe, None


def _run_with_limits(cmd, inp, cwd, time_limit):
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
        out, err = proc.communicate(input=inp, timeout=time_limit)
        if proc.returncode != 0:
            return {"verdict": "Runtime Error", "details": err}
        return {"verdict": "Passed", "output": out}
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"verdict": "Time Limit Exceeded"}


def normalize(text): return text.strip().replace("\r\n", "\n")


def run_test_cases(sub, tests, prob):
    tmp = SUBMISSIONS_DIR / f"{sub['participant_name']}_{int(time.time()*1000)}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        if sub["language"] == "python":
            script = tmp / "main.py"
            script.write_text(sub["code"])
            cmd = ["python", str(script)]
        elif sub["language"] == "cpp":
            exe, err = _compile_cpp(sub["code"], tmp)
            if err:
                return {"verdict": "Compilation Error", "details": err}
            cmd = [str(exe)]
        else:
            return {"verdict": "System Error", "details": "Unsupported language"}

        for i, t in enumerate(tests):
            res = _run_with_limits(cmd, t["input"], tmp, prob["time_limit"])
            if res["verdict"] != "Passed":
                return {"verdict": res["verdict"], "details": f"Failed on test {i+1}: {res.get('details','')}"}
            if normalize(res["output"]) != normalize(t["output"]):
                return {"verdict": "Wrong Answer", "details": f"Failed on test {i+1}"}
        return {"verdict": "Accepted"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_plagiarism(sub, scoreboard):
    pid = sub["problem_id"]
    me = sub["participant_name"]
    my_code = sub["code"]
    for user, data in scoreboard.items():
        if user == me:
            continue
        solved = data.get("problems_solved", {})
        if pid in solved:
            other_code = solved[pid].get("code")
            if not other_code:
                continue
            sim = SequenceMatcher(None, my_code, other_code).ratio()
            if sim >= SIMILARITY_THRESHOLD:
                msg = f"Submission {me} is {sim:.2%} similar to {user}"
                print("⚠️", msg)
                return True, msg
    return False, ""


def update_scoreboard(sub, verdict, details="", plag=False):
    board = load_json(SCOREBOARD_FILE)
    user = sub["participant_name"]
    pid = sub["problem_id"]

    # ensure user entry
    if user not in board:
        board[user] = {"score": 0, "problems_solved": {}}

    # record
    record = {
        "verdict": verdict,
        "timestamp": time.time(),
        "code": sub["code"],
    }
    if details:
        record["details"] = details

    board[user]["problems_solved"][pid] = record

    # update score only if accepted (and not plagiarism)
    if verdict == "Accepted" and not plag:
        board[user]["score"] = board[user].get("score", 0) + 100

    save_json_atomic(SCOREBOARD_FILE, board)


def judge_and_verify(sub):
    problems = load_json(PROBLEMS_FILE)
    prob = problems.get(sub["problem_id"])
    if not prob:
        return {"verdict": "System Error", "details": "Problem not found"}

    board = load_json(SCOREBOARD_FILE)
    plag, msg = check_plagiarism(sub, board)
    if plag:
        update_scoreboard(sub, "Plagiarism Detected", msg, plag=True)
        return {"verdict": "Plagiarism Detected", "details": msg}

    tests = prob.get("sample_test_cases", []) + prob.get("hidden_test_cases", [])
    result = run_test_cases(sub, tests, prob)
    verdict = result["verdict"]
    details = result.get("details", "")
    update_scoreboard(sub, verdict, details)
    return {"verdict": verdict, "details": details}


if __name__ == "__main__":
    s1 = {"participant_name": "manas", "problem_id": "P1", "language": "python", "code": "a,b=map(int,input().split());print(a+b)"}
    s2 = {"participant_name": "online", "problem_id": "P1", "language": "python", "code": "a,b=map(int,input().split());print(a+b)"}

    print(">>> First submission:", judge_and_verify(s1))
    print(">>> Second submission:", judge_and_verify(s2))
