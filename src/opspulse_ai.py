"""OPSPULSE AI: one place that loads every model once and answers the three questions the service desk asks.

  triage(text)                 -> category, priority, team, similar past tickets, likely fix, typical time, risk
  risk(priority, hours_open)   -> breach risk for a ticket that is still open, and whether to alert
  open_at(as_of)               -> every ticket open at a moment in time, with its risk status (for alerts)

Used by src/sla_alerts.py, src/api.py and the demo app, so they all give the same answers.
Everything is free and runs locally: the meaning model (BGE-small via fastembed) is only loaded when new
text has to be read.

Needs (created by earlier steps): data/processed/tickets_with_text.csv, data/processed/opspulse.db,
data/processed/ticket_embeddings.npy, models/semantic_classifier.joblib, models/ticket_classifier.joblib,
models/sla_risk_table.json
"""
import json
import sqlite3
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from similar_tickets import neighbours, suggest
from train_classifier import CORRECT_GROUP

TICKETS = "data/processed/tickets_with_text.csv"
DB_FILE = "data/processed/opspulse.db"
EMB_CACHE = "data/processed/ticket_embeddings.npy"
SEMANTIC_MODEL = "models/semantic_classifier.joblib"
KEYWORD_MODEL = "models/ticket_classifier.joblib"
RISK_TABLE = "models/sla_risk_table.json"


class OpsPulseAI:
    def __init__(self, root="."):
        root = Path(root)
        df = pd.read_csv(root / TICKETS)
        with sqlite3.connect(root / DB_FILE) as conn:
            extra = pd.read_sql("""SELECT i.incident_id, i.resolved_at, i.resolution_hours, i.sla_met, i.state,
                                          i.assigned_to, p.sla_target_hours
                                   FROM incidents i JOIN priorities p ON p.priority = i.priority""", conn)
            self.sla_target = dict(conn.execute("SELECT priority, sla_target_hours FROM priorities").fetchall())
        df = df.merge(extra, on="incident_id", how="left")
        df["opened_at"] = pd.to_datetime(df["opened_at"])
        df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce")
        self.tickets = df
        self.vecs = np.load(root / EMB_CACHE)
        self.resolved = df[df["resolution_hours"].notna()]
        self.semantic = joblib.load(root / SEMANTIC_MODEL)
        self.keyword = joblib.load(root / KEYWORD_MODEL)
        risk = json.loads((root / RISK_TABLE).read_text())
        self.risk_table = {p: {float(k): v for k, v in row.items()} for p, row in risk["risk"].items()}
        self.alert_point = risk["alert_point"]
        self.alert_at = risk["alert_at_risk"]
        self._embedder = None

    # ---- reading new text -------------------------------------------------------------
    def embed(self, text):
        if self._embedder is None:
            from fastembed import TextEmbedding
            self._embedder = TextEmbedding(self.semantic["embedding_model"])
        v = np.array(list(self._embedder.embed([text])), dtype=np.float32)[0]
        return v / np.linalg.norm(v)

    # ---- question 1: triage a new ticket ----------------------------------------------
    def triage(self, text):
        vec = self.embed(text)
        cat_model = self.semantic["category"]
        probs = cat_model.predict_proba([vec])[0]
        category = str(cat_model.classes_[probs.argmax()])
        priority = str(self.keyword["priority"].predict([text])[0])

        pos, sims = neighbours(vec, self.vecs[self.resolved.index])
        nb = self.resolved.iloc[pos].assign(similarity=sims)
        s = suggest(nb)
        target = self.sla_target[priority]
        return {
            "category": category,
            "category_confidence": round(float(probs.max()), 3),
            "priority": priority,
            "team": CORRECT_GROUP[category],
            "team_from_similar_tickets": s["team"],
            "likely_fix": s["likely_fix"],
            "typical_hours": round(s["typical_hours"], 1),
            "sla_target_hours": target,
            "breach_risk_at_start": self.risk_table[priority][0.1],
            "alert_if_still_open_after_hours": round(self.alert_point[priority] * target, 2),
            "similar_tickets": [
                {"incident_id": r["incident_id"], "similarity": round(float(r["similarity"]), 3),
                 "description": r["description"], "category": r["category"], "priority": r["priority"],
                 "fixed_by": r["assignment_group"], "hours": round(float(r["resolution_hours"]), 1),
                 "fix": r["resolution_note"]}
                for _, r in nb.head(3).iterrows()
            ],
        }

    # ---- question 2: risk for a ticket that is still open ------------------------------
    def risk(self, priority, hours_open):
        if priority not in self.sla_target:
            raise ValueError(f"priority must be one of {sorted(self.sla_target)}")
        target = self.sla_target[priority]
        used = hours_open / target
        if used >= 1:
            return {"priority": priority, "hours_open": hours_open, "sla_target_hours": target,
                    "sla_time_used": round(used, 3), "breach_risk": 1.0, "status": "Breached",
                    "hours_left": 0.0}
        step = min(max(np.floor(used * 10) / 10, 0.1), 0.9)  # nearest check-in at or below
        r = self.risk_table[priority][round(float(step), 1)]
        return {"priority": priority, "hours_open": hours_open, "sla_target_hours": target,
                "sla_time_used": round(used, 3), "breach_risk": r,
                "status": "Alert" if r >= self.alert_at else "OK",
                "hours_left": round(target - hours_open, 2)}

    # ---- question 3: everything open at a moment in time (for alerts) -----------------
    def open_at(self, as_of):
        as_of = pd.Timestamp(as_of)
        t = self.tickets
        mask = (t["opened_at"] <= as_of) & (t["resolved_at"].isna() | (t["resolved_at"] > as_of))
        o = t.loc[mask, ["incident_id", "opened_at", "priority", "category", "assignment_group",
                         "assigned_to", "description", "sla_met"]].copy()
        o["hours_open"] = ((as_of - o["opened_at"]).dt.total_seconds() / 3600).round(2)
        rows = [self.risk(p, h) for p, h in zip(o["priority"], o["hours_open"])]
        o["sla_time_used"] = [r["sla_time_used"] for r in rows]
        o["breach_risk"] = [r["breach_risk"] for r in rows]
        o["status"] = [r["status"] for r in rows]
        o["hours_left"] = [r["hours_left"] for r in rows]
        # Routing check: the AI category model suggests the right team; flag tickets sitting elsewhere
        predicted = self.semantic["category"].predict(self.vecs[o.index])
        o["suggested_team"] = [CORRECT_GROUP[c] for c in predicted]
        o["possibly_misrouted"] = o["suggested_team"] != o["assignment_group"]
        order = {"Alert": 0, "OK": 1, "Breached": 2}
        return o.sort_values(["status", "hours_left"], key=lambda c: c.map(order) if c.name == "status" else c)
