"""Run every query in a .sql file against the OPSPULSE database and print results.
Usage (from the project root):  python src/run_query.py sql/analytics_basic.sql
"""
import sqlite3
import sys

import pandas as pd

sql_text = open(sys.argv[1], encoding="utf-8").read()
conn = sqlite3.connect("data/processed/opspulse.db")
for block in sql_text.split(";"):
    lines = [l for l in block.strip().splitlines() if l.strip()]
    if not lines or all(l.startswith("--") for l in lines):
        continue
    print("\n".join(l for l in lines if l.startswith("--")))
    print(pd.read_sql("\n".join(l for l in lines if not l.startswith("--")), conn).to_string(index=False))
    print()
conn.close()
