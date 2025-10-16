"""
Shunyata Central Judge Server (CJS) - main.py
"""
import json
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from judge import judge_and_verify, load_problems, SCOREBOARD_FILE

app = FastAPI(title="Shunyata Decentralized Coding Contest Platform")
templates = Jinja2Templates(directory="templates")

class Submission(BaseModel):
    code: str
    problem_id: str
    participant_name: str
    language: str

@app.get("/", response_class=HTMLResponse)
async def get_problem_list(request: Request):
    problems = load_problems()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "problems": problems}
    )

@app.get("/problem/{problem_id}", response_class=HTMLResponse)
async def get_problem_details(request: Request, problem_id: str):
    problems = load_problems()
    problem = problems.get(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    return templates.TemplateResponse(
        "problem.html",
        {"request": request, "problem_id": problem_id, "problem": problem}
    )

@app.get("/scoreboard", response_class=HTMLResponse)
async def get_scoreboard_page(request: Request):
    return templates.TemplateResponse("scoreboard.html", {"request": request})

@app.get("/api/problems", response_model=Dict[str, Any])
async def api_get_problems():
    return load_problems()

@app.get("/api/scoreboard", response_class=JSONResponse)
async def api_get_scoreboard():
    if not SCOREBOARD_FILE.exists():
        return {}
    with open(SCOREBOARD_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

@app.post("/api/submit", response_class=JSONResponse)
async def api_submit_code(submission: Submission):
    try:
        result = judge_and_verify(submission.dict())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("🚀 Shunyata Central Judge Server (CJS) starting...")
    print("Access the contest UI at http://127.0.0.1:5000")
    print("The CEA should connect to this machine's LAN IP on port 5000.")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=5000)