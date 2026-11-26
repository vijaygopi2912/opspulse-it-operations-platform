"""OPSPULSE workforce analytics: is the work shared fairly, and how is each technician doing?

Answers the questions an IT service manager asks about people (not just tickets):
  - Which teams are overloaded for their size?          (tickets per technician)
  - Is work shared fairly inside each team?             (load vs team average)
  - Who resolves fastest, fairly compared?              (SLA time used: hours / SLA target)
  - Whose fixes hold?                                   (reopen rate)
  - Does a heavier workload go with worse SLA?          (correlation across technicians)

Input : data/processed/opspulse.db
Output: reports/workforce/workforce_analytics.xlsx  (Findings, Technician scorecard, Team capacity, Monthly workload)
        reports/workforce/team_capacity.png
        reports/workforce/technician_quadrant.png
Run from the project root:  python src/workforce_analytics.py
"""
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

DB_FILE = "data/processed/opspulse.db"
OUT_DIR = Path("reports/workforce")
SLA_TARGET = 0.90
MIN_TICKETS = 100  # only rank technicians with enough tickets to be meaningful

NAVY, BLUE, GREEN, AMBER, RED, GREY = "#10233F", "#3B82F6", "#22C55E", "#F59E0B", "#EF4444", "#94A3B8"
TEAM_COLOURS = {"Service Desk": "#1D4ED8", "Application Support": "#0EA5E9", "Network Team": "#14B8A6",
                "Security Operations": "#8B5CF6", "Desktop Support": "#F59E0B"}


def load(db_file):
    query = """
        SELECT i.incident_id, i.opened_at, i.resolved_at, i.priority, p.sla_target_hours,
               g.group_name AS team, i.assigned_to AS technician, i.reopen_count,
               i.resolution_hours, i.sla_met
        FROM incidents i
        JOIN assignment_groups g ON g.group_id = i.group_id
        JOIN priorities p        ON p.priority = i.priority
    """
    with sqlite3.connect(db_file) as conn:
        df = pd.read_sql(query, conn)
    df["opened_at"] = pd.to_datetime(df["opened_at"])
    df["month"] = df["opened_at"].dt.to_period("M").astype(str)
    # Priority-adjusted speed: 50% means the ticket used half of its SLA time
    df["sla_time_used"] = df["resolution_hours"] / df["sla_target_hours"]
    # Each technician's home team: where most of their tickets sit (ignoring tickets with no group)
    home = (df[df["team"] != "Unassigned"].groupby("technician")["team"]
            .agg(lambda s: s.value_counts().index[0]))
    df["home_team"] = df["technician"].map(home)
    return df


def technician_scorecard(df):
    g = df.groupby("technician")
    sc = pd.DataFrame({
        "Team": g["home_team"].first(),
        "Tickets": g.size(),
        "Open now": g["resolved_at"].apply(lambda s: s.isna().sum()),
        "SLA %": g["sla_met"].mean(),
        "Breaches": g["sla_met"].apply(lambda s: (s == 0).sum()),
        "Avg hours": g["resolution_hours"].mean(),
        "SLA time used": g["sla_time_used"].mean(),
        "Reopen rate": g["reopen_count"].apply(lambda s: (s > 0).mean()),
        "Urgent share (P1+P2)": g["priority"].apply(lambda s: s.isin(["P1", "P2"]).mean()),
    })
    team_avg = sc.groupby("Team")["Tickets"].transform("mean")
    sc["Load vs team avg"] = sc["Tickets"] / team_avg
    org_avg = sc["Tickets"].mean()
    sc["Load vs org avg"] = sc["Tickets"] / org_avg
    sc["Load flag"] = pd.cut(sc["Load vs org avg"], [0, 0.8, 1.2, 99], labels=["Light", "Normal", "Heavy"]).astype(str)
    return sc.sort_values("Tickets", ascending=False)


def team_capacity(df):
    d = df[df["team"] != "Unassigned"]
    g = d.groupby("team")
    cap = pd.DataFrame({
        "Technicians": g["technician"].nunique(),
        "Tickets": g.size(),
        "SLA %": g["sla_met"].mean(),
        "Breaches": g["sla_met"].apply(lambda s: (s == 0).sum()),
        "Open now": g["resolved_at"].apply(lambda s: s.isna().sum()),
    })
    cap["Tickets per technician"] = (cap["Tickets"] / cap["Technicians"]).round(0)
    # How many technicians each team would need to carry the org-wide average load
    org_per_tech = cap["Tickets"].sum() / cap["Technicians"].sum()
    cap["Technicians needed at avg load"] = (cap["Tickets"] / org_per_tech).round(1)
    return cap.sort_values("Tickets per technician", ascending=False)


def findings(sc, cap, df):
    out = []
    top, low = cap.iloc[0], cap.iloc[-1]
    ratio = top["Tickets per technician"] / low["Tickets per technician"]
    gap = top["Technicians needed at avg load"] - top["Technicians"]
    out.append(("Action", "Team capacity",
                f"{top.name} technicians each carry {top['Tickets per technician']:.0f} tickets, "
                f"{ratio:.1f}x the load in {low.name} ({low['Tickets per technician']:.0f}). At the average load "
                f"across all teams, {top.name} would need about {top['Technicians needed at avg load']:.1f} people "
                f"instead of {int(top['Technicians'])} (roughly {gap:.1f} more)."))

    max_dev = (sc["Load vs team avg"] - 1).abs().max()
    out.append(("On track" if max_dev <= 0.10 else "Watch", "Fairness inside teams",
                f"Inside each team, work is shared evenly: every technician is within {max_dev:.0%} of their team's average."))

    ranked = sc[sc["Tickets"] >= MIN_TICKETS]
    best, worst = ranked["SLA %"].idxmax(), ranked["SLA %"].idxmin()
    out.append(("Watch" if ranked.loc[worst, "SLA %"] < SLA_TARGET else "On track", "SLA by technician",
                f"Highest SLA: {best} ({ranked.loc[best, 'SLA %']:.1%}). Lowest: {worst} "
                f"({ranked.loc[worst, 'SLA %']:.1%}, {int(ranked.loc[worst, 'Breaches'])} breaches, "
                f"{ranked.loc[worst, 'Tickets']} tickets)."))

    hi, lo = ranked["Reopen rate"].idxmax(), ranked["Reopen rate"].idxmin()
    out.append(("Watch", "Fix quality",
                f"{hi} has the highest reopen rate ({ranked.loc[hi, 'Reopen rate']:.1%} of tickets reopened) and "
                f"{lo} the lowest ({ranked.loc[lo, 'Reopen rate']:.1%}). Worth a look at how fixes are verified."))

    r = ranked["Tickets"].corr(ranked["SLA %"])
    strength = "weak" if abs(r) < 0.3 else ("moderate" if abs(r) < 0.6 else "strong")
    direction = "lower" if r < 0 else "higher"
    out.append(("Info", "Workload vs SLA",
                f"Across {len(ranked)} technicians, more tickets goes with {direction} SLA "
                f"(correlation {r:.2f}, {strength}). With this few people, treat it as a signal, not proof."))

    no_group = int((df["team"] == "Unassigned").sum())
    out.append(("Watch", "Data quality",
                f"{no_group} tickets have a technician but no assignment group, so team totals slightly undercount; "
                f"technician totals include them."))
    return pd.DataFrame(out, columns=["Status", "Area", "Finding"])


# ---------------- charts ----------------
def chart_capacity(cap, path):
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    colours = [TEAM_COLOURS.get(t, GREY) for t in cap.index]
    labels = [f"{t} ({n})" for t, n in zip(cap.index, cap["Technicians"])]  # team (people)
    ax.barh(labels, cap["Tickets per technician"], color=colours)
    avg = cap["Tickets"].sum() / cap["Technicians"].sum()
    ax.axvline(avg, color=NAVY, linestyle="--", linewidth=1.2, zorder=0)  # behind the bars
    ax.text(avg + 3, len(cap) - 0.45, f"average {avg:.0f}", color=NAVY, fontsize=9)
    for y, v in enumerate(cap["Tickets per technician"]):
        ax.text(v - 6, y, f"{v:.0f}", va="center", ha="right", fontsize=10, color="white")
    ax.invert_yaxis()
    ax.set_xlim(0, cap["Tickets per technician"].max() * 1.3)
    ax.set_title("Tickets per technician, by team (number of people in brackets)", loc="left", fontsize=11)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_quadrant(sc, path):
    fig, ax = plt.subplots(figsize=(7.5, 5))
    for team, part in sc.groupby("Team"):
        ax.scatter(part["SLA time used"], part["SLA %"], s=part["Tickets"] * 1.6, alpha=0.75,
                   color=TEAM_COLOURS.get(team, GREY), label=team, edgecolor="white")
    placed = []  # put a label below its point when another labelled point is very close
    for name, row in sc.sort_values("SLA %", ascending=False).iterrows():
        x, y = row["SLA time used"], row["SLA %"]
        crowded = any(abs(x - px) < 0.004 and abs(y - py) < 0.004 for px, py in placed)
        ax.annotate(name, (x, y), xytext=(7, -13) if crowded else (7, 4), textcoords="offset points", fontsize=8)
        placed.append((x, y))
    ax.axhline(SLA_TARGET, color=AMBER, linestyle="--", linewidth=1)
    ax.axvline(sc["SLA time used"].median(), color=GREY, linestyle=":", linewidth=1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("SLA time used on average (left = faster)")
    ax.set_ylabel("SLA met")
    ax.set_title("Technicians: speed vs SLA (bubble size = tickets; amber line = 90% target)", loc="left", fontsize=10)
    ax.legend(fontsize=8, loc="lower left", markerscale=0.3, frameon=False)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------- Excel ----------------
HEADER = PatternFill("solid", fgColor=NAVY[1:])
STATUS = {"On track": "DCFCE7", "Watch": "FEF3C7", "Action": "FEE2E2", "Info": "DBEAFE"}


def write_sheet(writer, name, df, pct_cols=(), dec_cols=(), wrap_col=None):
    df.to_excel(writer, sheet_name=name, index=False)
    ws = writer.sheets[name]
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for j, col in enumerate(df.columns, 1):
        letter = get_column_letter(j)
        width = max(len(str(col)), *(len(f"{v}") for v in df[col].head(50))) + 2
        ws.column_dimensions[letter].width = min(max(width, 10), 60)
        for cell in ws[letter][1:]:
            if col in pct_cols:
                cell.number_format = "0.0%"
            elif col in dec_cols:
                cell.number_format = "0.00"
            if col == "Status" and cell.value in STATUS:
                cell.fill = PatternFill("solid", fgColor=STATUS[cell.value])
            if col == wrap_col:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    if wrap_col:
        ws.column_dimensions[get_column_letter(list(df.columns).index(wrap_col) + 1)].width = 110
    ws.freeze_panes = "A2"


def main():
    df = load(DB_FILE)
    sc = technician_scorecard(df)
    cap = team_capacity(df)
    find = findings(sc, cap, df)
    monthly = df.pivot_table(index="technician", columns="month", values="incident_id", aggfunc="count", fill_value=0)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chart_capacity(cap, OUT_DIR / "team_capacity.png")
    chart_quadrant(sc, OUT_DIR / "technician_quadrant.png")

    xlsx = OUT_DIR / "workforce_analytics.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        write_sheet(w, "Findings", find, wrap_col="Finding")
        write_sheet(w, "Technician scorecard", sc.reset_index().rename(columns={"technician": "Technician"}),
                    pct_cols=("SLA %", "SLA time used", "Reopen rate", "Urgent share (P1+P2)",
                              "Load vs team avg", "Load vs org avg"), dec_cols=("Avg hours",))
        write_sheet(w, "Team capacity", cap.reset_index().rename(columns={"team": "Team"}), pct_cols=("SLA %",))
        write_sheet(w, "Monthly workload", monthly.reset_index().rename(columns={"technician": "Technician"}))

    print("OPSPULSE workforce analytics\n")
    print("Team capacity:")
    print(cap[["Technicians", "Tickets", "Tickets per technician", "SLA %", "Breaches"]]
          .to_string(formatters={"SLA %": "{:.1%}".format}))
    print("\nFindings:")
    for st, area, text in find.itertuples(index=False):
        print(f"  [{st}] {area}: {text}")
    print(f"\nSaved: {xlsx}")
    print(f"Saved: {OUT_DIR / 'team_capacity.png'}, {OUT_DIR / 'technician_quadrant.png'}")


if __name__ == "__main__":
    main()
