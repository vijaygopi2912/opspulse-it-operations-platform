"""Load the cleaned incidents into a SQLite database.

Input : data/processed/incidents_clean.csv, sql/schema.sql
Output: data/processed/opspulse.db
Run from the project root:  python src/load_database.py
"""
import sqlite3
from pathlib import Path

import pandas as pd

DB_FILE = Path("data/processed/opspulse.db")
df = pd.read_csv("data/processed/incidents_clean.csv")

conn = sqlite3.connect(DB_FILE)
conn.executescript(Path("sql/schema.sql").read_text())

# Lookup table 1: priorities (each priority has one SLA target)
priorities = df[["priority", "sla_target_hours"]].drop_duplicates()
priorities.to_sql("priorities", conn, if_exists="append", index=False)

# Lookup table 2: assignment groups get a numeric id
groups = pd.DataFrame({"group_name": sorted(df["assignment_group"].unique())})
groups.to_sql("assignment_groups", conn, if_exists="append", index=False)
group_ids = pd.read_sql("SELECT group_id, group_name FROM assignment_groups", conn)

# Main table: swap the group name for its id, drop the repeated SLA column
inc = df.merge(group_ids, left_on="assignment_group", right_on="group_name")
inc = inc.drop(columns=["assignment_group", "group_name", "sla_target_hours"])
inc["bad_dates"] = inc["bad_dates"].astype(int)
inc["sla_met"] = inc["sla_met"].map({True: 1, False: 0, "True": 1, "False": 0})
inc.to_sql("incidents", conn, if_exists="append", index=False)

conn.commit()
for t in ("priorities", "assignment_groups", "incidents"):
    n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"{t}: {n} rows")
conn.close()
