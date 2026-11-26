"""Export dashboard-ready tables from the OPSPULSE database to Excel.

Input : data/processed/opspulse.db
Output: reports/opspulse_dashboard_data.xlsx  (sheets: Incidents, Priorities, Groups)
Run from the project root:  python src/export_for_powerbi.py
"""
import sqlite3

import pandas as pd

conn = sqlite3.connect("data/processed/opspulse.db")

incidents = pd.read_sql(
    """
    SELECT i.incident_id, i.opened_at, i.resolved_at, i.priority, i.category,
           i.subcategory, g.group_name AS assignment_group, i.assigned_to,
           i.caller_department, i.location, i.state, i.reopen_count,
           i.resolution_hours, i.sla_met, i.bad_dates
    FROM incidents i
    JOIN assignment_groups g ON g.group_id = i.group_id
    """,
    conn,
)
priorities = pd.read_sql("SELECT priority, sla_target_hours FROM priorities", conn)
groups = pd.read_sql("SELECT group_id, group_name FROM assignment_groups", conn)
conn.close()

# Real dates + helper columns so Power BI can slice by day and month easily
incidents["opened_at"] = pd.to_datetime(incidents["opened_at"])
incidents["resolved_at"] = pd.to_datetime(incidents["resolved_at"])
incidents["opened_date"] = incidents["opened_at"].dt.normalize()
incidents["opened_month"] = incidents["opened_at"].dt.to_period("M").dt.to_timestamp()
incidents["is_open"] = incidents["state"].isin(["In Progress", "On Hold"]).astype(int)

with pd.ExcelWriter("reports/opspulse_dashboard_data.xlsx", engine="openpyxl",
                    datetime_format="yyyy-mm-dd hh:mm", date_format="yyyy-mm-dd") as xl:
    incidents.to_excel(xl, sheet_name="Incidents", index=False)
    priorities.to_excel(xl, sheet_name="Priorities", index=False)
    groups.to_excel(xl, sheet_name="Groups", index=False)
    for ws in xl.book.worksheets:          # readable column widths
        for col in ws.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
            ws.column_dimensions[col[0].column_letter].width = min(width + 2, 28)

print("Incidents:", len(incidents), "rows | open:", int(incidents["is_open"].sum()))
print("Saved reports/opspulse_dashboard_data.xlsx")
