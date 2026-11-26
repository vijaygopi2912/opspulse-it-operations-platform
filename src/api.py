"""OPSPULSE triage API: the AI as a web service that other tools (a portal, ServiceNow, a chatbot) could call.

Pages
  GET  /                  the demo web app (src/static/index.html)
  GET  /docs              interactive API documentation

Endpoints
  GET  /health            is the service up, and how many tickets does it know
  POST /triage            {"text": "..."} -> category, priority, team, similar tickets, likely fix, risk
  POST /risk              {"priority": "P3", "hours_open": 6.5} -> breach risk and Alert / OK / Breached
  GET  /alerts?as_of=...  tickets that need action at a moment in time

Setup (once):  pip install fastapi uvicorn
Run (from the project root):
  uvicorn api:app --app-dir src --port 8000
Then open http://127.0.0.1:8000 for the demo app, or http://127.0.0.1:8000/docs to try every endpoint.
Stop the server with Ctrl+C in the terminal.
"""
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from opspulse_ai import OpsPulseAI

app = FastAPI(
    title="OPSPULSE Triage API",
    version="1.0",
    description="Free, local AI for IT service management: ticket triage, similar fixes and SLA breach risk.",
)
ai = OpsPulseAI()  # loads models once, when the server starts
STATIC = Path(__file__).resolve().parent / "static"


class TriageRequest(BaseModel):
    text: str = Field(..., min_length=5, max_length=2000,
                      examples=["Outlook keeps asking me for my password since this morning"])


class RiskRequest(BaseModel):
    priority: str = Field(..., examples=["P3"])
    hours_open: float = Field(..., ge=0, examples=[6.5])


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "tickets_known": len(ai.tickets), "resolved_tickets_searchable": len(ai.resolved)}


@app.post("/triage")
def triage(req: TriageRequest):
    return ai.triage(req.text.strip())


@app.post("/risk")
def risk(req: RiskRequest):
    try:
        return ai.risk(req.priority.upper().strip(), req.hours_open)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/alerts")
def alerts(as_of: str = Query("2026-09-03 14:00", description='Moment to check, e.g. "2026-10-13 16:00"')):
    try:
        ts = pd.Timestamp(as_of)
    except ValueError:
        raise HTTPException(status_code=422, detail="as_of must look like 2026-10-13 16:00")
    o = ai.open_at(ts)
    cols = ["incident_id", "priority", "category", "assignment_group", "assigned_to",
            "hours_open", "hours_left", "breach_risk", "status", "suggested_team", "possibly_misrouted",
            "description"]
    alert_rows = o[o["status"] == "Alert"][cols]
    return {
        "as_of": str(ts),
        "needs_action_now": int((o["status"] == "Alert").sum()),
        "on_track": int((o["status"] == "OK").sum()),
        "already_breached": int((o["status"] == "Breached").sum()),
        "alerts": alert_rows.to_dict(orient="records"),
    }
