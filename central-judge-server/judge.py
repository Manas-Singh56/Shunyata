"""
Shunyata Central Judge (judge.py)
Handles judging, storage, plagiarism detection, and robust scoreboard updates.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple
from difflib import SequenceMatcher

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not found. Memory limits won't be enforced.")

# === CONSTANTS ===
CONTEST_DATA_DIR = Path("./contest_data")
SUBMISSIONS_DIR = Path("./submissions")
PROBLEMS_FILE = CONTEST_DATA_DIR / "problems.json"
SCOREBOARD_FILE = CONTEST_DATA_DIR / "scoreboard.json"
SIMILARITY_THRESHOLD = 0.9  # 90%

CONTEST_DATA_DIR.mkdir(exist_ok=True)
SUBMISSIONS_DIR.mkdir(exist_ok=True)


# === UTILITIES ===
def load_problems() -> Dict[str, Any]:
    if not PROBLEMS_FILE.exists():
        return {}
    try:
        with open(PROBLEMS_FILE, 'r', encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_submission(submission_data: Dict[str, Any]) -> Path:
    """Save submission code to ./submissions/ for later plagiarism checking."""
    # Keep submissions as JSON so we can store metadata too
    filename = f"{submission_data['participant_name']}_{submission_data['problem_id']}_{int(time.time())}.json"
    filepath = SUBMISSIONS_DIR / filename
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(submission_data, f, indent=4)
        return filepath
    except Exception as e:
        print(f"[WARN] Failed to save submission to {filepath}: {e}")
        return filepath


def check_plagiarism(submission_data: Dict[str, Any]) -> Dict[str, Any]:
    """Check against all stored submissions for similarity (same problem)."""
    current_code = submission_data.get("code", "")
    problem_id = submission_data.get("problem_id")
    author = submission_data.get("participant_name")

    for file in SUBMISSIONS_DIR.glob("*.json"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                old = json.load(f)
            if old.get("problem_id") != problem_id or old.get("participant_name") == author:
                continue
            similarity = SequenceMatcher(None, current_code, old.get("code", "")).ratio()
            if similarity >= SIMILARITY_THRESHOLD:
                msg = f"⚠️ Plagiarism detected: {author} similar to {old.get('participant_name')} ({similarity:.2%})"
                print(msg)
                return {"verdict": "Plagiarism Detected", "details": msg}
        except Exception:
            continue
    return {"verdict": "Clean"}


# ============================
# === SCOREBOARD HELPERS ====
# ============================
def _load_scoreboard() -> Dict[str, Any]:
    """Safely load scoreboard JSON, return empty dict on any error."""
    if not SCOREBOARD_FILE.exists() or SCOREBOARD_FILE.stat().st_size == 0:
        return {}
    try:
        with open(SCOREBOARD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_scoreboard_atomic(data: Dict[str, Any]):
    """Write scoreboard atomically to avoid corrupt state."""
    tmp = SCOREBOARD_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, SCOREBOARD_FILE)


def update_scoreboard(participant: str, problem_id: str, verdict: str, details: str = "", code: str = None):
    """
    Robustly update scoreboard:
    - Store per-participant `problems_solved` entries with verdict, details and timestamp.
    - Score = 100 * number of unique problems with 'Accepted' verdict.
    - If a problem was already Accepted earlier, do not double-count.
    """
    try:
        scoreboard = _load_scoreboard()

        if participant not in scoreboard:
            scoreboard[participant] = {"score": 0, "problems_solved": {}}

        user_entry = scoreboard[participant]
        problems_solved = user_entry.setdefault("problems_solved", {})

        # If the problem already has an Accepted record, keep it (do not overwrite)
        existing = problems_solved.get(problem_id)
        if existing and existing.get("verdict") == "Accepted":
            # Already accepted earlier; do not change verdict or increase score
            print(f"[INFO] Participant '{participant}' already accepted problem '{problem_id}' earlier; skipping scoreboard change.")
        else:
            # Record/overwrite the verdict for this attempt
            problems_solved[problem_id] = {
                "verdict": verdict,
                "details": details,
                "timestamp": time.time()
            }
            if code is not None:
                # store code snapshot (optional; may grow file size)
                problems_solved[problem_id]["code"] = code

        # Recalculate score from scratch to avoid double-counting
        new_score = 0
        for pid, rec in problems_solved.items():
            if rec.get("verdict") == "Accepted":
                new_score += 100
        user_entry["score"] = new_score

        # Persist atomically
        _save_scoreboard_atomic(scoreboard)
        print(f"[SCORE] Updated scoreboard for '{participant}': {new_score} points")

    except Exception as e:
        print(f"[ERROR] update_scoreboard failed: {e}")


# ============================
# === COMPILATION & RUNNING =
# ============================
def _compile_cpp(source_code: str, exec_dir: Path) -> Tuple[Path, str]:
    source_file = exec_dir / "main.cpp"
    source_file.write_text(source_code, encoding="utf-8")
    executable = exec_dir / ("main.exe" if os.name == 'nt' else "main")
    compile_cmd = ["g++", "-std=c++17", "-O2", str(source_file), "-o", str(executable)]
    try:
        proc = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return None, proc.stderr
        return executable, None
    except FileNotFoundError:
        return None, "g++ compiler not found."
    except subprocess.TimeoutExpired:
        return None, "Compilation timed out."


def _run_with_limits(command: list, input_data: str, cwd: Path, time_limit: float, mem_limit_mb: int) -> Dict[str, Any]:
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
        p = psutil.Process(process.pid) if PSUTIL_AVAILABLE else None
        if p:
            mem_limit_bytes = mem_limit_mb * 1024 * 1024
            while process.poll() is None:
                try:
                    if p.memory_info().rss > mem_limit_bytes:
                        p.kill()
                        return {"verdict": "Memory Limit Exceeded"}
                    time.sleep(0.01)
                except psutil.NoSuchProcess:
                    break
        stdout, stderr = process.communicate(input=input_data, timeout=time_limit)
        if process.returncode != 0:
            return {"verdict": "Runtime Error", "details": stderr}
        return {"verdict": "Passed", "output": stdout}
    except subprocess.TimeoutExpired:
        process.kill()
        return {"verdict": "Time Limit Exceeded"}
    except Exception as e:
        return {"verdict": "System Error", "details": str(e)}


def _normalize_output(text: str) -> str:
    return text.strip().replace('\r\n', '\n')


# ============================
# === RUN TEST CASES ========
# ============================
def run_test_cases(submission_data: Dict[str, Any], test_cases: List[Dict[str, str]], problem_info: Dict[str, Any]) -> Dict[str, Any]:
    run_id = f"{submission_data['participant_name']}_{submission_data['problem_id']}_{int(time.time() * 1000)}"
    exec_dir = SUBMISSIONS_DIR / run_id  # temporary execution dir inside submissions to ease debugging
    exec_dir.mkdir(parents=True, exist_ok=True)
    try:
        lang = submission_data.get("language", "").lower()
        if lang == "cpp":
            executable_path, compile_error = _compile_cpp(submission_data["code"], exec_dir)
            if compile_error:
                return {"verdict": "Compilation Error", "details": compile_error}
            run_command = [str(executable_path)]
        elif lang == "python":
            script_path = exec_dir / "main.py"
            script_path.write_text(submission_data["code"], encoding="utf-8")
            run_command = ["python", "main.py"]
        else:
            return {"verdict": "System Error", "details": "Unsupported language"}

        for i, test_case in enumerate(test_cases):
            run_result = _run_with_limits(run_command, test_case.get("input", ""), exec_dir, problem_info.get("time_limit", 2), problem_info.get("memory_limit", 256))
            if run_result["verdict"] != "Passed":
                run_result["details"] = f"Failed on test case #{i + 1}. {run_result.get('details', '')}"
                return run_result
            expected = _normalize_output(test_case.get("output", ""))
            actual = _normalize_output(run_result.get("output", ""))
            if expected != actual:
                return {"verdict": "Wrong Answer", "details": f"Failed on test case #{i + 1}", "expected": expected, "got": actual}
        return {"verdict": "Accepted"}
    finally:
        # Keep exec_dir so you can inspect failed runs during debugging.
        # If you prefer automatic cleanup, uncomment the next line.
        shutil.rmtree(exec_dir, ignore_errors=True)


# ============================
# === MAIN JUDGE FUNCTION ===
# ============================
def judge_and_verify(submission_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    submission_data is expected to have:
    {
      "participant_name": str,
      "problem_id": str,
      "language": "cpp"|"python",
      "code": str
    }
    """
    # Step 1: Save submission for persistent record (plagiarism checking)
    try:
        save_submission(submission_data)
    except Exception as e:
        print(f"[WARN] Could not persist submission: {e}")

    # Step 2: Plagiarism check (quick, on persisted submissions)
    try:
        plag = check_plagiarism(submission_data)
        if plag.get("verdict") == "Plagiarism Detected":
            # Update scoreboard record with plagiarism verdict (no score)
            update_scoreboard(submission_data["participant_name"], submission_data["problem_id"], "Plagiarism Detected", details=plag.get("details", ""), code=submission_data.get("code"))
            return plag
    except Exception as e:
        print(f"[WARN] Plagiarism check failed: {e}")

    # Step 3: Load problem and tests
    problems = load_problems()
    problem_info = problems.get(submission_data["problem_id"])
    if not problem_info:
        return {"verdict": "System Error", "details": "Problem not found."}

    test_cases = problem_info.get("sample_test_cases", []) + problem_info.get("hidden_test_cases", [])
    if not test_cases:
        return {"verdict": "System Error", "details": "No test cases found for this problem."}

    # Step 4: Execute tests
    result = run_test_cases(submission_data, test_cases, problem_info)

    # Step 5: Update scoreboard (and store code snapshot in problems_solved entry)
    update_scoreboard(submission_data["participant_name"], submission_data["problem_id"], result["verdict"], details=result.get("details", ""), code=submission_data.get("code"))

    return result
