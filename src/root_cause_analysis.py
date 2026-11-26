"""Root cause analysis: find the recurring problems behind the incidents (ITIL problem management).

Steps:
  1. Group tickets by MEANING with no labels at all (K-Means on the free BGE-small embeddings).
  2. Name each group by its most distinctive words, ignoring greetings, urgency and sign-offs.
  3. Rank the groups as problem candidates by impact: hours lost beyond SLA, breaches, reopened tickets.
  4. Spike check: did any group have a month with far more tickets than expected? (Poisson test)
  5. Systemic check: when SLA dropped in March and August, was it one problem or all of them?
     If almost every group got slower together, the cause is capacity or process, not one technical fault.

Input : data/processed/tickets_with_text.csv, data/processed/opspulse.db, the saved embeddings
        (created by semantic_classifier.py; made here with the free model if missing)
Output: reports/rca/root_cause_analysis.xlsx  (Findings, Problem candidates, Group details, Monthly volume)
        reports/rca/problem_impact.png
        reports/rca/sla_by_group_month.png
Run from the project root:  python src/root_cause_analysis.py
"""
import math
import re
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics import adjusted_rand_score

TICKETS = "data/processed/tickets_with_text.csv"
DB_FILE = "data/processed/opspulse.db"
EMB_CACHE = Path("data/processed/ticket_embeddings.npy")
OUT_DIR = Path("reports/rca")
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
SLA_TARGET = 0.90
SLOW_MONTHS = ("2026-03", "2026-08")  # the SLA dips found in the SQL analysis

# 28 groups: checked against the known subcategories, about 79% of each group is one specific problem.
# With real data you would tune this with a silhouette score and a human review of the group names.
N_GROUPS = 28

# Words that say nothing about the problem itself (greetings, urgency, sign-offs, time phrases)
BOILERPLATE = {
    "hi", "hello", "dear", "team", "it", "support", "good", "morning", "thanks", "thank", "regards", "sent",
    "iphone", "urgent", "urgently", "rush", "priority", "low", "quite", "critical", "help", "please", "advance",
    "deadline", "afternoon", "blocking", "work", "today", "customers", "affected", "right", "ceo", "needs",
    "fixed", "immediately", "department", "presentation", "client", "minutes", "whole", "people", "problem",
    "just", "letting", "know", "whenever", "time", "week", "later", "look", "someone", "since", "yesterday",
    "update", "night", "leave", "came", "days", "last", "doesn", "don", "won", "isn", "ve", "ll", "production",
    "ahmed", "fatima", "ravi", "sarah", "mohammed", "anita", "james", "layla", "arjun", "noura", "having",
}


def load():
    df = pd.read_csv(TICKETS)
    with sqlite3.connect(DB_FILE) as conn:
        extra = pd.read_sql("""SELECT i.incident_id, i.resolution_hours, i.sla_met, i.reopen_count,
                                      p.sla_target_hours
                               FROM incidents i JOIN priorities p ON p.priority = i.priority""", conn)
    df = df.merge(extra, on="incident_id", how="left")
    df["month"] = pd.to_datetime(df["opened_at"]).dt.to_period("M").astype(str)
    df["hours_over_sla"] = (df["resolution_hours"] - df["sla_target_hours"]).clip(lower=0)
    if EMB_CACHE.exists() and len(np.load(EMB_CACHE)) == len(df):
        vecs = np.load(EMB_CACHE)
    else:
        from fastembed import TextEmbedding
        print("Embedding tickets with the free model (first run downloads it)...")
        v = np.array(list(TextEmbedding(EMBED_MODEL).embed(df["description"].tolist())), dtype=np.float32)
        vecs = v / np.linalg.norm(v, axis=1, keepdims=True)
        np.save(EMB_CACHE, vecs)
    return df, vecs


def name_groups(df):
    """Name each group by the words most distinctive to it (class-based TF-IDF)."""
    docs = df.groupby("group")["description"].apply(lambda s: " ".join(s).lower())
    vec = TfidfVectorizer(stop_words=list(ENGLISH_STOP_WORDS | BOILERPLATE), token_pattern=r"[a-z][a-z0-9\-]{1,}",
                          sublinear_tf=True)
    m = vec.fit_transform(docs)
    terms = np.array(vec.get_feature_names_out())
    names = {}
    for g, row in zip(docs.index, m.toarray()):
        names[g] = ", ".join(terms[np.argsort(-row)[:3]])
    return names


def poisson_tail(k, mu):
    """Probability of seeing k or more tickets when mu are expected (Poisson)."""
    return 1 - sum(math.exp(-mu) * mu ** i / math.factorial(i) for i in range(k))


def main():
    df, vecs = load()
    df["group"] = KMeans(N_GROUPS, n_init=10, random_state=42).fit_predict(vecs)
    names = name_groups(df)
    df["group_name"] = df["group"].map(names)

    # How well do the label-free groups match the known subcategories? (validation only)
    t = pd.crosstab(df["group"], df["subcategory"])
    purity = t.max(axis=1).sum() / t.values.sum()
    ari = adjusted_rand_score(df["subcategory"], df["group"])

    # ---- Problem candidates ranked by impact --------------------------------------------
    g = df.groupby("group")
    prob = pd.DataFrame({
        "Problem group (key words)": g["group_name"].first(),
        "Mostly": t.idxmax(axis=1),
        "Purity": t.max(axis=1) / t.sum(axis=1),
        "Tickets": g.size(),
        "Breaches": g["sla_met"].apply(lambda s: (s == 0).sum()),
        "SLA %": g["sla_met"].mean(),
        "Hours over SLA": g["hours_over_sla"].sum(),
        "Reopened tickets": g["reopen_count"].apply(lambda s: (s > 0).sum()),
        "Avg hours": g["resolution_hours"].mean(),
        "Main team": g["correct_group"].agg(lambda s: s.value_counts().index[0]),
        "Example ticket": g["description"].agg(lambda s: s.iloc[0]),
    })
    prob["Impact score"] = (prob["Hours over SLA"] / prob["Hours over SLA"].max() * 50
                            + prob["Breaches"] / prob["Breaches"].max() * 30
                            + prob["Reopened tickets"] / prob["Reopened tickets"].max() * 20).round(1)
    prob = prob.sort_values("Impact score", ascending=False)
    prob.insert(0, "Rank", range(1, len(prob) + 1))

    # ---- Spike check: any group with a month far above its expected share? --------------
    month_share = df["month"].value_counts(normalize=True)
    monthly = pd.crosstab(df["group"], df["month"])
    spikes, tests = [], 0
    for grp, row in monthly.iterrows():
        for month, k in row.items():
            mu = row.sum() * month_share[month]
            tests += 1
            p = poisson_tail(int(k), mu)
            if k >= 1.8 * mu and p < 0.01 / (N_GROUPS * len(month_share)):  # strict: many tests at once
                spikes.append((names[grp], month, int(k), round(mu, 1)))

    # ---- Systemic check: did SLA fall in the slow months across (almost) all groups? ------
    slow = df["month"].isin(SLOW_MONTHS)
    by = df.groupby(["group", slow])["sla_met"].mean().unstack()
    by.columns = ["Other months", "Mar + Aug"]
    by["Drop (pts)"] = (by["Other months"] - by["Mar + Aug"]) * 100
    dropped = int((by["Drop (pts)"] > 0).sum())
    hours = df.groupby(["group", slow])["resolution_hours"].mean().unstack()
    slowdown = (hours[True] / hours[False]).median()

    # ---- Findings ---------------------------------------------------------------------------
    top = prob.head(3)
    findings = [
        ("Info", "Grouping",
         f"Tickets were grouped by meaning into {N_GROUPS} recurring problem groups with no labels. Checked "
         f"against the known subcategories, {purity:.0%} of each group is one specific problem (ARI {ari:.2f})."),
        ("Action", "Top problem candidates",
         "Highest impact: " + "; ".join(f"{r['Mostly']} ('{r['Problem group (key words)']}': {int(r['Breaches'])} "
                                        f"breaches, {r['Hours over SLA']:.0f} h over SLA)"
                                        for _, r in top.iterrows()) + ". Raise these as problem records."),
        ("On track" if not spikes else "Watch", "Volume spikes",
         "No problem group had a month with significantly more tickets than expected, so no single fault "
         "suddenly broke." if not spikes else
         "Spikes: " + "; ".join(f"{n} in {m} ({k} vs {mu} expected)" for n, m, k, mu in spikes)),
        ("Action", "March and August SLA dips",
         f"SLA fell in {dropped} of {N_GROUPS} problem groups in March and August, and tickets took about "
         f"{slowdown:.1f}x longer across the board. A drop this widespread points to a systemic cause such as "
         f"staffing or a process change, not one technical fault: check rosters, leave and changes in those months."),
    ]
    find = pd.DataFrame(findings, columns=["Status", "Area", "Finding"])

    # ---- Charts -------------------------------------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    top10 = prob.head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    labels = [f"{m}  ({w})" for m, w in zip(top10["Mostly"], top10["Problem group (key words)"])]
    ax.barh(labels, top10["Impact score"], color="#3B82F6")
    for y, (s, b) in enumerate(zip(top10["Impact score"], top10["Breaches"])):
        ax.text(s + 0.5, y, f"{s:.0f}  ({int(b)} breaches)", va="center", fontsize=8)
    ax.set_xlim(0, top10["Impact score"].max() * 1.25)
    ax.set_title("Top 10 problem candidates by impact score", loc="left", fontsize=10)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "problem_impact.png", dpi=130)
    plt.close(fig)

    order = prob["Mostly"] + "  (" + prob["Problem group (key words)"] + ")"
    sla_m = df.pivot_table(index="group", columns="month", values="sla_met", aggfunc="mean").loc[prob.index]
    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.imshow(sla_m.values, cmap="RdYlGn", vmin=0.5, vmax=1.0, aspect="auto")
    ax.set_yticks(range(len(sla_m)), order.values, fontsize=7)
    ax.set_xticks(range(len(sla_m.columns)), [pd.Period(m).strftime("%b") for m in sla_m.columns], fontsize=8)
    ax.set_title("SLA % by problem group and month (red = low SLA)",
                 loc="left", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.03, format=matplotlib.ticker.PercentFormatter(1.0))
    fig.tight_layout()
    fig.savefig(OUT_DIR / "sla_by_group_month.png", dpi=130)
    plt.close(fig)

    # ---- Excel ----------------------------------------------------------------------------------
    details = df[["group_name", "subcategory", "incident_id", "priority", "description", "resolution_hours",
                  "sla_met", "resolution_note"]].sort_values(["group_name", "subcategory"])
    vol = monthly.loc[prob.index]
    vol.index = order.values
    xlsx = OUT_DIR / "root_cause_analysis.xlsx"
    navy = PatternFill("solid", fgColor="10233F")
    status_fill = {"On track": "DCFCE7", "Watch": "FEF3C7", "Action": "FEE2E2", "Info": "DBEAFE"}
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        find.to_excel(w, "Findings", index=False)
        prob.to_excel(w, "Problem candidates", index=False)
        details.to_excel(w, "Group details", index=False)
        vol.to_excel(w, "Monthly volume", index_label="Problem group")
        by.round(3).set_index(prob.reindex(by.index)["Mostly"] + "  (" + by.index.map(names) + ")") \
            .to_excel(w, "Slow months check", index_label="Problem group")
        for ws in w.book.worksheets:
            for c in ws[1]:
                c.font, c.fill = Font(bold=True, color="FFFFFF"), navy
                c.alignment = Alignment(wrap_text=True, vertical="center")
            for col in ws.columns:
                letter = get_column_letter(col[0].column)
                width = max(len(str(c.value)) for c in col[:60] if c.value is not None) + 2
                ws.column_dimensions[letter].width = min(max(width, 9), 70)
            ws.freeze_panes = "A2"
        ws = w.book["Findings"]
        ws.column_dimensions["C"].width = 120
        for row in ws.iter_rows(min_row=2):
            row[2].alignment = Alignment(wrap_text=True, vertical="top")
            if row[0].value in status_fill:
                row[0].fill = PatternFill("solid", fgColor=status_fill[row[0].value])
        ws = w.book["Problem candidates"]
        for col_name, fmt in (("Purity", "0%"), ("SLA %", "0.0%"), ("Hours over SLA", "0"), ("Avg hours", "0.00")):
            idx = list(prob.columns).index(col_name) + 1
            for cell in ws[get_column_letter(idx)][1:]:
                cell.number_format = fmt

    print("OPSPULSE root cause analysis\n")
    print(f"Grouped {len(df)} tickets into {N_GROUPS} problem groups (purity {purity:.0%} vs known subcategories)\n")
    print("Top 5 problem candidates:")
    for _, r in prob.head(5).iterrows():
        print(f"  {r['Rank']}. {r['Mostly']:<20} '{r['Problem group (key words)']}'  {int(r['Tickets'])} tickets, "
              f"{int(r['Breaches'])} breaches, {r['Hours over SLA']:.0f} h over SLA, impact {r['Impact score']:.0f}")
    print("\nFindings:")
    for st, area, text in find.itertuples(index=False):
        print(f"  [{st}] {area}: {text}")
    print(f"\nSaved: {xlsx}")
    print(f"Saved: {OUT_DIR / 'problem_impact.png'}, {OUT_DIR / 'sla_by_group_month.png'}")


if __name__ == "__main__":
    main()
