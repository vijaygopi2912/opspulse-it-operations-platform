"""Generate a synthetic (fake) ITSM incident dataset for OPSPULSE.

Output: data/raw/incidents_raw.csv
The data is deliberately a little messy (blanks, duplicates, inconsistent
labels, bad dates) so that the cleaning step has real work to do.
Run from the project root:  python src/generate_data.py
"""
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
N_ROWS = 3000
START = datetime(2026, 1, 1)
END = datetime(2026, 10, 31)

ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = ROOT / "data" / "raw" / "incidents_raw.csv"

# priority -> (SLA target in hours, share of tickets, typical resolve hours)
PRIORITIES = {
    "P1": (1, 0.05, 0.5),
    "P2": (4, 0.15, 1.8),
    "P3": (8, 0.45, 3.0),
    "P4": (24, 0.35, 8.0),
}

# Months where the service desk struggled (tickets took longer to resolve)
MONTH_SLOWDOWN = {3: 1.6, 8: 1.5}

CATEGORIES = {
    "Network": ["VPN", "Wi-Fi", "Switch outage", "Slow connection"],
    "Hardware": ["Laptop", "Printer", "Monitor", "Docking station"],
    "Software": ["Office 365", "ERP", "Browser", "Installation request"],
    "Access": ["Password reset", "Account locked", "New access request"],
    "Email": ["Outlook", "Shared mailbox", "Spam"],
    "Security": ["Phishing", "Antivirus", "Suspicious login"],
}

GROUPS = ["Service Desk", "Network Team", "Desktop Support",
          "Application Support", "Security Operations"]
GROUP_FOR_CATEGORY = {
    "Network": "Network Team", "Hardware": "Desktop Support",
    "Software": "Application Support", "Access": "Service Desk",
    "Email": "Service Desk", "Security": "Security Operations",
}

AGENTS = {
    "Service Desk": ["Aisha K", "Rahul S", "Maria L"],
    "Network Team": ["Omar H", "Vikram P"],
    "Desktop Support": ["Sara M", "John D", "Fatima R"],
    "Application Support": ["Priya N", "Khalid A"],
    "Security Operations": ["Daniel W", "Noor S"],
}

DEPARTMENTS = ["Finance", "HR", "Sales", "Operations", "IT", "Legal", "Marketing"]
LOCATIONS = ["Dubai", "Abu Dhabi", "Sharjah", "Remote"]
STATES = [("Closed", 0.80), ("Resolved", 0.15), ("In Progress", 0.04), ("On Hold", 0.01)]

HEADER = ["incident_id", "opened_at", "resolved_at", "priority", "category",
          "subcategory", "assignment_group", "assigned_to", "caller_department",
          "location", "state", "sla_target_hours", "reopen_count",
          "short_description"]


def pick_weighted(pairs):
    r, total = random.random(), 0
    for value, weight in pairs:
        total += weight
        if r <= total:
            return value
    return pairs[-1][0]


def random_open_time():
    """Random timestamp, weighted towards working hours on weekdays."""
    while True:
        t = START + timedelta(seconds=random.randint(0, int((END - START).total_seconds())))
        if t.weekday() >= 5 and random.random() < 0.8:
            continue
        if not (8 <= t.hour <= 18) and random.random() < 0.7:
            continue
        return t


def make_row(n):
    priority = pick_weighted([(p, v[1]) for p, v in PRIORITIES.items()])
    sla_hours, _, typical = PRIORITIES[priority]
    category = random.choice(list(CATEGORIES))
    sub = random.choice(CATEGORIES[category])
    group = GROUP_FOR_CATEGORY[category]
    if random.random() < 0.12:
        group = random.choice(GROUPS)
    state = pick_weighted(STATES)
    opened = random_open_time()
    resolved = ""
    if state in ("Closed", "Resolved"):
        hours = random.lognormvariate(0, 0.7) * typical * MONTH_SLOWDOWN.get(opened.month, 1.0)
        resolved = opened + timedelta(hours=hours)
    return {
        "incident_id": f"INC{100000 + n}",
        "opened_at": opened,
        "resolved_at": resolved,
        "priority": priority,
        "category": category,
        "subcategory": sub,
        "assignment_group": group,
        "assigned_to": random.choice(AGENTS[group]),
        "caller_department": random.choice(DEPARTMENTS),
        "location": random.choice(LOCATIONS),
        "state": state,
        "sla_target_hours": sla_hours,
        "reopen_count": pick_weighted([(0, 0.9), (1, 0.08), (2, 0.02)]),
        "short_description": f"{category} issue - {sub}",
    }


def fmt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value


def add_mess(rows):
    """Inject realistic data-quality problems."""
    for r in rows:
        x = random.random()
        if x < 0.03:
            r["assignment_group"] = ""                      # missing group
        if random.random() < 0.03:
            r["priority"] = random.choice(
                [r["priority"].lower(), r["priority"] + " ", "Priority " + r["priority"][1]])
        if random.random() < 0.02 and r["resolved_at"]:     # different date format
            r["resolved_at"] = datetime.strptime(r["resolved_at"], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
        if random.random() < 0.01 and r["resolved_at"]:     # resolved before opened
            r["resolved_at"] = (datetime.strptime(r["opened_at"], "%Y-%m-%d %H:%M:%S")
                                - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        if random.random() < 0.02:
            r["caller_department"] = ""                     # missing department
    dupes = random.sample(rows, int(len(rows) * 0.02))      # exact duplicate rows
    rows.extend(dict(d) for d in dupes)
    random.shuffle(rows)
    return rows


def main():
    random.seed(SEED)
    rows = []
    for n in range(1, N_ROWS + 1):
        row = make_row(n)
        row["opened_at"] = fmt(row["opened_at"])
        row["resolved_at"] = fmt(row["resolved_at"])
        rows.append(row)
    rows = add_mess(rows)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT_FILE}")


if __name__ == "__main__":
    main()
