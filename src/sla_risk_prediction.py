"""SLA risk prediction: warn about tickets likely to breach SLA while there is still time to act.

Approach (and why):
  - All tickets open today are already past their SLA, so the useful question is an EARLY WARNING:
    "this ticket is still open, how likely is it to breach?"
  - Tested like real life: learn from January to August, then replay September and October as unseen future.
  - Four approaches are compared on the same unseen months (AUC: 0.5 = coin flip, 1.0 = perfect):
      1. At intake, priority only
      2. At intake, machine learning on every field known when the ticket opens
      3. Risk table: priority x share of SLA time already used, learned from history
      4. Machine learning on every field PLUS share of SLA time already used
  - If machine learning does not beat the simple table, the simple, explainable table is the one to use.
  - Alert rule: warn when a ticket's breach risk reaches 50%. The backtest measures how many breaches were
    warned about in advance, how much warning there was, and how many warnings were real.

Input : data/processed/opspulse.db
Output: models/sla_risk_table.json                 (risk table and alert points, reused by later steps)
        reports/sla_risk/sla_risk_prediction.xlsx  (Findings, Model comparison, Risk table, Alert backtest)
        reports/sla_risk/risk_curves.png
        reports/sla_risk/model_comparison.png
Run from the project root:  python src/sla_risk_prediction.py
"""
import json
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

DB_FILE = "data/processed/opspulse.db"
OUT_DIR = Path("reports/sla_risk")
TABLE_FILE = Path("models/sla_risk_table.json")
TRAIN_LAST_MONTH = 8          # learn from Jan to Aug, test on Sep and Oct
STEPS = np.round(np.arange(0.1, 1.0, 0.1), 1)   # check-ins at 10%, 20%, ... 90% of SLA time used
ALERT_AT = 0.5                # warn when breach risk reaches 50%
FIELDS = ["priority", "category", "team", "caller_department", "location"]
PRIORITY_COLOURS = {"P1": "#EF4444", "P2": "#F59E0B", "P3": "#3B82F6", "P4": "#22C55E"}


def load():
    q = """SELECT i.incident_id, i.opened_at, i.priority, i.category, g.group_name AS team,
                  i.caller_department, i.location, i.resolution_hours, i.sla_met, p.sla_target_hours
           FROM incidents i
           JOIN assignment_groups g ON g.group_id = i.group_id
           JOIN priorities p        ON p.priority = i.priority"""
    with sqlite3.connect(DB_FILE) as conn:
        df = pd.read_sql(q, conn)
    df["opened_at"] = pd.to_datetime(df["opened_at"])
    df = df[df["sla_met"].notna()].copy()           # only tickets with a known SLA outcome
    df["breached"] = 1 - df["sla_met"].astype(int)
    df["month"] = df["opened_at"].dt.month
    df["hour"] = df["opened_at"].dt.hour
    df["weekday"] = df["opened_at"].dt.weekday
    return df


def checkpoints(df):
    """One row per ticket per check-in at which it was STILL OPEN (the moment a warning could be given)."""
    rows = []
    for f in STEPS:
        d = df[df["resolution_hours"] > f * df["sla_target_hours"]].copy()
        d["sla_used"] = f
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


def features(d, columns=None, with_time=False):
    x = pd.get_dummies(d[FIELDS].astype(str))
    x["hour"], x["weekday"] = d["hour"].values, d["weekday"].values
    if with_time:
        x["sla_used"] = d["sla_used"].values
    return x if columns is None else x.reindex(columns=columns, fill_value=0)


def risk_table(train_ck):
    """Share of still-open tickets that went on to breach, by priority and share of SLA time used."""
    return train_ck.pivot_table(index="priority", columns="sla_used", values="breached", aggfunc="mean")


def main():
    df = load()
    train, test = df[df["month"] <= TRAIN_LAST_MONTH], df[df["month"] > TRAIN_LAST_MONTH]
    ck = checkpoints(df)
    ck_train, ck_test = ck[ck["month"] <= TRAIN_LAST_MONTH], ck[ck["month"] > TRAIN_LAST_MONTH]

    # ---- 1 + 2: at intake ----------------------------------------------------------------
    pri_tr, pri_te = pd.get_dummies(train["priority"]), pd.get_dummies(test["priority"])
    auc_priority = roc_auc_score(test["breached"],
                                 LogisticRegression().fit(pri_tr, train["breached"]).predict_proba(pri_te)[:, 1])
    Xtr = features(train)
    ml_intake = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=42)
    ml_intake.fit(Xtr, train["breached"])
    auc_ml_intake = roc_auc_score(test["breached"], ml_intake.predict_proba(features(test, Xtr.columns))[:, 1])

    # ---- 3 + 4: while the ticket is open -------------------------------------------------
    table = risk_table(ck_train)
    table_risk = [table.loc[p, f] for p, f in zip(ck_test["priority"], ck_test["sla_used"])]
    auc_table = roc_auc_score(ck_test["breached"], table_risk)
    Xc = features(ck_train, with_time=True)
    ml_flight = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=42)
    ml_flight.fit(Xc, ck_train["breached"])
    auc_ml_flight = roc_auc_score(ck_test["breached"],
                                  ml_flight.predict_proba(features(ck_test, Xc.columns, with_time=True))[:, 1])
    comparison = pd.DataFrame({
        "Approach": ["At intake: priority only", "At intake: ML on all ticket fields",
                     "While open: risk table (priority x SLA time used)",
                     "While open: ML on all fields + SLA time used"],
        "AUC on Sep-Oct (unseen)": [auc_priority, auc_ml_intake, auc_table, auc_ml_flight],
    }).round(3)

    # ---- Alert rule and backtest on Sep-Oct ----------------------------------------------
    alert_point = {}
    for p in table.index:
        hits = [f for f in table.columns if table.loc[p, f] >= ALERT_AT]
        alert_point[p] = float(hits[0]) if hits else float(table.columns[-1])
    bt = []
    for p, part in test.groupby("priority"):
        a = alert_point[p]
        alerted = part["resolution_hours"] > a * part["sla_target_hours"]   # still open when the alert fires
        breached = part["breached"] == 1
        bt.append({
            "Priority": p,
            "SLA target (hrs)": part["sla_target_hours"].iloc[0],
            "Alert when SLA time used reaches": a,
            "Warning before breach (hrs)": round((1 - a) * part["sla_target_hours"].iloc[0], 1),
            "Tickets": len(part),
            "Alerts raised": int(alerted.sum()),
            "Breaches": int(breached.sum()),
            "Breaches warned in advance": int((alerted & breached).sum()),
            "Alerts that were real breaches": round((alerted & breached).sum() / max(alerted.sum(), 1), 3),
        })
    bt = pd.DataFrame(bt)
    tot_alerts, tot_breach = bt["Alerts raised"].sum(), bt["Breaches"].sum()
    tot_warned = bt["Breaches warned in advance"].sum()
    days = (test["opened_at"].max() - test["opened_at"].min()).days + 1

    # ---- Findings ----------------------------------------------------------------------------
    best_ml_gain = auc_ml_flight - auc_table
    find = pd.DataFrame([
        ("Info", "At intake",
         f"When a ticket is opened, its details do not predict a breach: ML on every field scored AUC {auc_ml_intake:.2f} "
         f"(0.5 is a coin flip) and priority alone {auc_priority:.2f}. P1 breaches most often (about 1 in 4)."),
        ("Info", "While open",
         f"Risk rises sharply with time already used: of tickets still open at 50% of their SLA time, "
         f"{ck_train.loc[ck_train['sla_used'] == 0.5, 'breached'].mean():.0%} went on to breach; at 80%, "
         f"{ck_train.loc[ck_train['sla_used'] == 0.8, 'breached'].mean():.0%}."),
        ("On track" if best_ml_gain < 0.02 else "Watch", "Simple beats complex",
         f"The simple risk table scored AUC {auc_table:.2f}; machine learning with every field scored {auc_ml_flight:.2f}. "
         + ("ML scored lower: it picks up patterns in fields that carry no real signal. So the simple, "
            "explainable table is used." if best_ml_gain < 0 else
            "ML adds almost nothing, so the simple, explainable table is used." if best_ml_gain < 0.02 else
            "ML adds a little; consider it if the extra complexity is worth it.")),
        ("Action", "Early-warning rule",
         f"Warn at the SLA-time point where risk reaches {ALERT_AT:.0%} ("
         + ", ".join(f"{p} at {alert_point[p]:.0%}" for p in sorted(alert_point)) +
         f"). Replayed on September and October it warned about {tot_warned} of {tot_breach} breaches before they "
         f"happened (every breach passes the alert point, so the real test is the false-alarm rate): "
         f"{tot_alerts / tot_breach:.1f} alerts per real breach ({tot_alerts / days:.1f} alerts a day), with "
         + ", ".join(f"{r['Priority']} {r['Warning before breach (hrs)']} h" for _, r in bt.iterrows())
         + " of warning."),
        ("Watch", "Today's backlog",
         "All tickets open now are already past their SLA, so the alerts matter for new tickets; the backlog itself "
         "is listed in the monthly report (Open Backlog sheet)."),
    ], columns=["Status", "Area", "Finding"])

    # ---- Save model, charts, Excel ----------------------------------------------------------
    TABLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TABLE_FILE.write_text(json.dumps({
        "description": "Probability that a ticket still open at a given share of its SLA time goes on to breach",
        "trained_on": "Jan-Aug 2026", "alert_at_risk": ALERT_AT,
        "risk": {p: {f"{f:.1f}": round(float(table.loc[p, f]), 3) for f in table.columns} for p in table.index},
        "alert_point": alert_point,
    }, indent=2))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for p in table.index:
        ax.plot(table.columns * 100, table.loc[p].values, marker="o", label=p, color=PRIORITY_COLOURS.get(p))
    ax.axhline(ALERT_AT, color="#10233F", linestyle="--", linewidth=1)
    ax.text(11, ALERT_AT + 0.02, "alert threshold", fontsize=8, color="#10233F")
    ax.set_xlabel("Share of SLA time already used while the ticket is still open (%)")
    ax.set_ylabel("Chance it goes on to breach")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_ylim(0, 1)
    ax.legend(frameon=False)
    ax.set_title("Breach risk rises as SLA time runs out (learned from Jan to Aug)", loc="left", fontsize=10)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "risk_curves.png", dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    vals = comparison["AUC on Sep-Oct (unseen)"].values
    ax.barh(comparison["Approach"], vals, color=["#94A3B8", "#94A3B8", "#1D4ED8", "#3B82F6"])
    ax.axvline(0.5, color="#64748B", linestyle=":", linewidth=1)
    for y, v in enumerate(vals):
        ax.text(v + 0.005, y, f"{v:.2f}", va="center", fontsize=9)
    ax.set_xlim(0.4, max(vals) + 0.08)
    ax.invert_yaxis()
    ax.set_title("Breach prediction on unseen months (AUC)", loc="left", fontsize=10)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "model_comparison.png", dpi=130)
    plt.close(fig)

    risk_sheet = table.copy()
    risk_sheet.columns = [f"{int(c * 100)}% used" for c in risk_sheet.columns]
    xlsx = OUT_DIR / "sla_risk_prediction.xlsx"
    navy = PatternFill("solid", fgColor="10233F")
    status_fill = {"On track": "DCFCE7", "Watch": "FEF3C7", "Action": "FEE2E2", "Info": "DBEAFE"}
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        find.to_excel(w, "Findings", index=False)
        comparison.to_excel(w, "Model comparison", index=False)
        risk_sheet.to_excel(w, "Risk table", index_label="Priority")
        bt.to_excel(w, "Alert backtest", index=False)
        for ws in w.book.worksheets:
            for c in ws[1]:
                c.font, c.fill = Font(bold=True, color="FFFFFF"), navy
                c.alignment = Alignment(wrap_text=True, vertical="center")
            for col in ws.columns:
                letter = get_column_letter(col[0].column)
                width = max(len(str(c.value)) for c in col if c.value is not None) + 2
                ws.column_dimensions[letter].width = min(max(width, 10), 60)
        ws = w.book["Findings"]
        ws.column_dimensions["C"].width = 120
        for row in ws.iter_rows(min_row=2):
            row[2].alignment = Alignment(wrap_text=True, vertical="top")
            row[0].fill = PatternFill("solid", fgColor=status_fill.get(row[0].value, "FFFFFF"))
        for row in w.book["Risk table"].iter_rows(min_row=2, min_col=2):
            for cell in row:
                cell.number_format = "0%"
        ws = w.book["Alert backtest"]
        for col_name in ("Alert when SLA time used reaches", "Alerts that were real breaches"):
            idx = list(bt.columns).index(col_name) + 1
            for cell in ws[get_column_letter(idx)][1:]:
                cell.number_format = "0%"

    print("OPSPULSE SLA risk prediction (learn Jan-Aug, test on Sep-Oct)\n")
    print(comparison.to_string(index=False))
    print("\nRisk that a still-open ticket breaches, by share of SLA time used:")
    print(risk_sheet.to_string(float_format=lambda v: f"{v:.0%}"))
    print("\nAlert backtest on Sep-Oct:")
    print(bt.to_string(index=False))
    print("\nFindings:")
    for st, area, text in find.itertuples(index=False):
        print(f"  [{st}] {area}: {text}")
    print(f"\nSaved: {TABLE_FILE}, {xlsx}, {OUT_DIR}/risk_curves.png, {OUT_DIR}/model_comparison.png")


if __name__ == "__main__":
    main()
