"""OPSPULSE automated monthly ITSM management report.

Reads the SQLite database and produces, for one reporting month:
  - an Excel workbook  (summary, trends, priority and group performance,
                        open backlog, SLA breach list, embedded charts)
  - a 2-page PDF summary for managers

Input : data/processed/opspulse.db
Output: reports/output/OPSPULSE_ITSM_Report_<YYYY-MM>.xlsx
        reports/output/OPSPULSE_ITSM_Report_<YYYY-MM>.pdf

Run from the project root:
  python src/generate_report.py                  # latest month in the data
  python src/generate_report.py --month 2026-08  # any other month
"""
import argparse
import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw charts to files, no window needed
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

DB_FILE = Path("data/processed/opspulse.db")
OUT_DIR = Path("reports/output")
SLA_TARGET = 0.90  # 90% of tickets should meet their SLA

# Colours shared with the Power BI dashboard
NAVY, BLUE, GREEN, AMBER, RED, GREY = "#10233F", "#3B82F6", "#22C55E", "#F59E0B", "#EF4444", "#64748B"


# --------------------------------------------------------------------------
# 1. Load data
# --------------------------------------------------------------------------
def load_incidents(db_file):
    """One row per incident, with group name and SLA target joined in (SQL JOIN)."""
    query = """
        SELECT i.incident_id, i.opened_at, i.resolved_at, i.priority, p.sla_target_hours,
               i.category, g.group_name AS assignment_group, i.assigned_to,
               i.caller_department, i.state, i.bad_dates, i.resolution_hours, i.sla_met
        FROM incidents i
        JOIN assignment_groups g ON g.group_id = i.group_id
        JOIN priorities p        ON p.priority = i.priority
    """
    with sqlite3.connect(db_file) as conn:
        df = pd.read_sql(query, conn)
    df["opened_at"] = pd.to_datetime(df["opened_at"])
    df["resolved_at"] = pd.to_datetime(df["resolved_at"])
    df["month"] = df["opened_at"].dt.to_period("M")
    return df


# --------------------------------------------------------------------------
# 2. Calculations
# --------------------------------------------------------------------------
def kpis(df):
    """Headline numbers for any slice of incidents.

    SLA is measured only on tickets that have an SLA result (sla_met not blank):
    open tickets and the rows with invalid dates have none.
    """
    measured = df["sla_met"].notna()
    total = len(df)
    open_n = int(df["resolved_at"].isna().sum())
    sla_pct = df.loc[measured, "sla_met"].mean() if measured.any() else float("nan")
    return {
        "Total incidents": total,
        "Open incidents": open_n,
        "Closed incidents": total - open_n,
        "SLA compliance": sla_pct,
        "SLA breaches": int((df["sla_met"] == 0).sum()),
        "Avg resolution (hrs)": df["resolution_hours"].mean(),
    }


def status(sla):
    """Same traffic-light rule as the dashboard."""
    if pd.isna(sla):
        return "Info"
    if sla >= SLA_TARGET:
        return "On track"
    if sla >= SLA_TARGET - 0.05:
        return "Watch"
    return "Action"


def performance_by(df, column):
    """Incidents, open, SLA %, breaches and average hours per value of `column`."""
    g = df.groupby(column)
    out = pd.DataFrame({
        "Incidents": g.size(),
        "Open": g["resolved_at"].apply(lambda s: s.isna().sum()),
        "SLA %": g["sla_met"].mean(),
        "Breaches": g["sla_met"].apply(lambda s: (s == 0).sum()),
        "Avg hrs": g["resolution_hours"].mean(),
    })
    out["Status"] = out["SLA %"].apply(status)
    return out


def monthly_trend(df, last_month):
    rows = []
    for m, part in df[df["month"] <= last_month].groupby("month"):
        k = kpis(part)
        rows.append({"Month": str(m), "Incidents": k["Total incidents"], "Closed": k["Closed incidents"],
                     "SLA %": k["SLA compliance"], "Breaches": k["SLA breaches"],
                     "Avg hrs": k["Avg resolution (hrs)"]})
    return pd.DataFrame(rows)


def open_backlog(df, as_of):
    """Tickets that were still open at `as_of`: opened before it, not resolved by then."""
    still_open = (df["opened_at"] <= as_of) & (df["resolved_at"].isna() | (df["resolved_at"] > as_of))
    b = df.loc[still_open, ["incident_id", "opened_at", "priority", "sla_target_hours",
                            "assignment_group", "assigned_to", "category", "state"]].copy()
    b["Age (hrs)"] = ((as_of - b["opened_at"]).dt.total_seconds() / 3600).round(1)
    b["Past SLA target"] = b["Age (hrs)"] > b["sla_target_hours"]
    return b.sort_values("Age (hrs)", ascending=False)


def findings(cur, prev, by_group, by_priority, backlog, month, prev_month):
    """Plain-English observations, each calculated from the data, with a status."""
    out = []
    kc, kp = kpis(cur), kpis(prev)

    if kp["Total incidents"]:
        ch = (kc["Total incidents"] - kp["Total incidents"]) / kp["Total incidents"]
        st = "On track" if ch <= 0 else ("Watch" if ch <= 0.10 else "Action")
        out.append((st, "Volume trend",
                    f"Incident volume {'increased' if ch >= 0 else 'decreased'} {abs(ch):.1%} in {month.strftime('%B')} "
                    f"({kc['Total incidents']} vs {kp['Total incidents']} in {prev_month.strftime('%B')})."))

    if not pd.isna(kc["SLA compliance"]):
        txt = f"SLA compliance was {kc['SLA compliance']:.1%} in {month.strftime('%B')} (target {SLA_TARGET:.0%})"
        if not pd.isna(kp["SLA compliance"]):
            pts = (kc["SLA compliance"] - kp["SLA compliance"]) * 100
            txt += f", {'up' if pts >= 0 else 'down'} {abs(pts):.1f} points on {prev_month.strftime('%B')}"
        out.append((status(kc["SLA compliance"]), "SLA trend", txt + "."))

    if kc["SLA breaches"]:
        top = by_group.sort_values("Breaches", ascending=False).iloc[0]
        out.append((top["Status"], "Breach hotspot",
                    f"{top.name} had the most SLA breaches: {int(top['Breaches'])} "
                    f"({top['Breaches'] / kc['SLA breaches']:.0%} of the month's {kc['SLA breaches']}), "
                    f"SLA {top['SLA %']:.1%}."))

    worst = by_priority.dropna(subset=["SLA %"]).sort_values("SLA %").iloc[0]
    if worst["SLA %"] < SLA_TARGET:
        out.append((worst["Status"], "Priority risk",
                    f"{worst.name} had the lowest SLA compliance at {worst['SLA %']:.1%}, "
                    f"{(SLA_TARGET - worst['SLA %']) * 100:.1f} points below target."))
    else:
        out.append(("On track", "Priority risk", f"All priorities met the {SLA_TARGET:.0%} SLA target."))

    overdue = int(backlog["Past SLA target"].sum())
    over_30d = int((backlog["Age (hrs)"] > 30 * 24).sum())
    oldest = backlog["Age (hrs)"].max() / 24 if len(backlog) else 0
    out.append(("Action" if overdue else "On track", "Open backlog",
                f"{len(backlog)} incidents open at month end, {overdue} past their SLA target; "
                f"{over_30d} open for over 30 days (oldest {oldest:.0f} days)."))
    return pd.DataFrame(out, columns=["Status", "Area", "Finding"])


# --------------------------------------------------------------------------
# 3. Charts (returned as PNG bytes so they can be reused in Excel and the PDF)
# --------------------------------------------------------------------------
def style_axes(ax, title):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color="#1F2937")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors="#374151", labelsize=9)


def to_png(fig):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def chart_trend(trend, month):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    colors = [NAVY if m == str(month) else BLUE for m in trend["Month"]]
    labels = [pd.Period(m).strftime("%b") for m in trend["Month"]]
    ax.bar(labels, trend["Incidents"], color=colors)
    for x, v in zip(labels, trend["Incidents"]):
        ax.text(x, v * 0.06, str(v), ha="center", color="white", fontsize=8)
    style_axes(ax, "Monthly incidents (bars) and SLA compliance (line)")
    ax2 = ax.twinx()
    ax2.plot(labels, trend["SLA %"], color=GREEN, marker="o", linewidth=2)
    ax2.axhline(SLA_TARGET, color=AMBER, linestyle="--", linewidth=1.5)
    ax2.text(-0.45, SLA_TARGET + 0.006, "90% target", color=AMBER, fontsize=8, ha="left")
    ax2.set_ylim(0.6, 1.0)
    ax2.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax2.spines["top"].set_visible(False)
    return to_png(fig)


def chart_priority(by_priority, month):
    fig, ax = plt.subplots(figsize=(4.6, 3.4))
    colors = [{"On track": GREEN, "Watch": AMBER, "Action": RED}.get(s, GREY) for s in by_priority["Status"]]
    ax.bar(by_priority.index, by_priority["SLA %"], color=colors)
    for x, v in zip(by_priority.index, by_priority["SLA %"]):
        ax.text(x, v + 0.01, f"{v:.0%}", ha="center", fontsize=9)
    ax.axhline(SLA_TARGET, color=AMBER, linestyle="--", linewidth=1.5)
    ax.set_ylim(0, 1.08)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    style_axes(ax, f"SLA compliance by priority, {month.strftime('%b %Y')}")
    return to_png(fig)


def chart_groups(by_group, month):
    data = by_group.sort_values("Breaches")
    fig, ax = plt.subplots(figsize=(4.6, 3.4))
    ax.barh(data.index, data["Breaches"], color=RED)
    for y, v in zip(data.index, data["Breaches"]):
        ax.text(v + 0.2, y, str(int(v)), va="center", fontsize=9)
    style_axes(ax, f"SLA breaches by assignment group, {month.strftime('%b %Y')}")
    return to_png(fig)


# --------------------------------------------------------------------------
# 4. Excel workbook
# --------------------------------------------------------------------------
HEADER_FILL = PatternFill("solid", fgColor=NAVY[1:])
STATUS_FILL = {s: PatternFill("solid", fgColor=c) for s, c in
               {"On track": "DCFCE7", "Watch": "FEF3C7", "Action": "FEE2E2", "Info": "DBEAFE"}.items()}


NICE_NAMES = {"incident_id": "Incident", "opened_at": "Opened", "resolved_at": "Resolved", "priority": "Priority",
              "sla_target_hours": "SLA target (hrs)", "resolution_hours": "Resolution (hrs)",
              "assignment_group": "Assignment group", "assigned_to": "Assigned to", "category": "Category",
              "state": "State"}


def write_table(ws, df, start_row=1, start_col=1, formats=None):
    """Write a DataFrame with a navy header row; formats = {column: excel number format}."""
    formats = formats or {}
    for j, name in enumerate(df.columns, start_col):
        c = ws.cell(row=start_row, column=j, value=name)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, row in enumerate(df.itertuples(index=False), start_row + 1):
        for j, (name, value) in enumerate(zip(df.columns, row), start_col):
            if isinstance(value, pd.Timestamp):
                value = value.to_pydatetime()
            elif pd.isna(value) if not isinstance(value, (list, dict)) else False:
                value = None
            c = ws.cell(row=i, column=j, value=value)
            if name in formats:
                c.number_format = formats[name]
            if name == "Status" and value in STATUS_FILL:
                c.fill = STATUS_FILL[value]
    return start_row + len(df) + 1


def autosize(ws, min_width=9, max_width=60):
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        longest = max((len(str(c.value)) for c in col if c.value is not None), default=0)
        ws.column_dimensions[letter].width = max(min_width, min(max_width, longest + 2))


def build_excel(path, month, kpi_table, find, trend, by_priority, by_group, backlog, breaches, charts):
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "OPSPULSE  |  Monthly ITSM Management Report"
    ws["A1"].font = Font(bold=True, size=16, color=NAVY[1:])
    ws["A2"] = f"Reporting month: {month.strftime('%B %Y')}    ·    Generated: {datetime.now():%d %b %Y %H:%M}"
    ws["A2"].font = Font(italic=True, color="64748B")

    pct = "0.0%"
    row = write_table(ws, kpi_table, start_row=4, formats={
        "This month": "#,##0.00", "Previous month": "#,##0.00", "Year to date": "#,##0.00"})
    # percentage rows need their own format
    for r in range(5, row):
        if ws.cell(row=r, column=1).value == "SLA compliance":
            for c in (2, 3, 5):
                ws.cell(row=r, column=c).number_format = pct
            ws.cell(row=r, column=4).number_format = '+0.0" pts";-0.0" pts"'
        elif ws.cell(row=r, column=1).value != "Avg resolution (hrs)":
            for c in (2, 3, 5):
                ws.cell(row=r, column=c).number_format = "#,##0"
            ws.cell(row=r, column=4).number_format = "+0.0%;-0.0%"
        else:
            ws.cell(row=r, column=4).number_format = "+0.0%;-0.0%"

    ws.cell(row=row + 1, column=1, value="Key findings").font = Font(bold=True, size=12, color=NAVY[1:])
    first = row + 2
    write_table(ws, find, start_row=first)
    # the Finding text is long: give it columns C to H, merged, with wrapping
    for r in range(first, first + len(find) + 1):
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=8)
        for c in (1, 2):
            ws.cell(row=r, column=c).alignment = Alignment(vertical="center")
        ws.cell(row=r, column=3).alignment = Alignment(wrap_text=True, vertical="center")
        if r > first:
            ws.row_dimensions[r].height = 32
    for letter, width in zip("ABCDEFGH", (24, 16, 16, 16, 16, 12, 12, 12)):
        ws.column_dimensions[letter].width = width
    # charts below the findings
    anchor = row + 4 + len(find)
    for k, png in enumerate(charts):
        img = XLImage(BytesIO(png))
        img.width, img.height = img.width * 0.45, img.height * 0.45
        ws.add_image(img, f"A{anchor + k * 22}")

    sheets = [
        ("Monthly Trend", trend, {"SLA %": pct, "Avg hrs": "0.00"}),
        ("By Priority", by_priority.reset_index().rename(columns={"priority": "Priority",
                                                                    "sla_target_hours": "SLA target (hrs)"}),
         {"SLA %": pct, "Avg hrs": "0.00"}),
        ("By Group", by_group.reset_index().rename(columns={"assignment_group": "Assignment group"}),
         {"SLA %": pct, "Avg hrs": "0.00"}),
        ("Open Backlog", backlog.rename(columns=NICE_NAMES), {"Opened": "dd-mmm-yyyy hh:mm"}),
        ("SLA Breaches", breaches.rename(columns=NICE_NAMES),
         {"Opened": "dd-mmm-yyyy hh:mm", "Resolved": "dd-mmm-yyyy hh:mm"}),
    ]
    for title, df, fmt in sheets:
        s = wb.create_sheet(title)
        write_table(s, df, formats=fmt)
        s.freeze_panes = "A2"
        autosize(s)
    for sheet in wb.worksheets:  # print each sheet landscape, one page wide
        sheet.page_setup.orientation = "landscape"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
    wb.save(path)


# --------------------------------------------------------------------------
# 5. PDF summary
# --------------------------------------------------------------------------
def build_pdf(path, month, kc, kp, find, charts):
    with PdfPages(path) as pdf:
        # Page 1: KPIs and findings
        fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape
        fig.text(0.05, 0.93, "OPSPULSE  |  Monthly ITSM Management Report", fontsize=20,
                 fontweight="bold", color=NAVY)
        fig.text(0.05, 0.895, f"Reporting month: {month.strftime('%B %Y')}   ·   Generated {datetime.now():%d %b %Y %H:%M}",
                 fontsize=10, color=GREY)
        tiles = [
            ("Total incidents", f"{kc['Total incidents']:,}", kc["Total incidents"], kp["Total incidents"], "pct"),
            ("Open at month end", f"{kc['Open incidents']:,}", None, None, None),
            ("SLA compliance", f"{kc['SLA compliance']:.1%}", kc["SLA compliance"], kp["SLA compliance"], "pts"),
            ("SLA breaches", f"{kc['SLA breaches']:,}", kc["SLA breaches"], kp["SLA breaches"], "pct"),
            ("Avg resolution", f"{kc['Avg resolution (hrs)']:.2f} hrs", kc["Avg resolution (hrs)"],
             kp["Avg resolution (hrs)"], "pct"),
        ]
        for i, (label, value, c, p, kind) in enumerate(tiles):
            x = 0.05 + i * 0.185
            fig.patches.append(plt.Rectangle((x, 0.68), 0.17, 0.17, transform=fig.transFigure,
                                             facecolor="#F1F5F9", edgecolor="#CBD5E1"))
            fig.text(x + 0.01, 0.815, label, fontsize=10, color=GREY)
            colour = NAVY
            if label == "SLA compliance":
                colour = {"On track": GREEN, "Watch": AMBER, "Action": RED}[status(kc["SLA compliance"])]
            fig.text(x + 0.01, 0.735, value, fontsize=20, fontweight="bold", color=colour)
            if kind and p:
                delta = (c - p) * 100 if kind == "pts" else (c - p) / p
                txt = f"{'▲' if delta >= 0 else '▼'} {abs(delta):.1f} pts" if kind == "pts" else \
                      f"{'▲' if delta >= 0 else '▼'} {abs(delta):.1%}"
                fig.text(x + 0.01, 0.695, f"{txt} vs {(month - 1).strftime('%b')}", fontsize=9, color=GREY)

        fig.text(0.05, 0.6, "Key findings", fontsize=14, fontweight="bold", color=NAVY)
        y = 0.55
        for st, area, text in find.itertuples(index=False):
            colour = {"On track": GREEN, "Watch": AMBER, "Action": RED}.get(st, BLUE)
            fig.text(0.05, y, f"● {st}", fontsize=11, color=colour, fontweight="bold")
            fig.text(0.16, y, area, fontsize=11, fontweight="bold", color="#1F2937")
            fig.text(0.29, y, text, fontsize=11, color="#1F2937", wrap=True)
            y -= 0.075
        fig.text(0.05, 0.04, "Source: OPSPULSE synthetic ITSM dataset. SLA % is measured on tickets with an SLA "
                 "result (open tickets excluded). Status: green ≥ 90%, amber 85–90%, red < 85%.",
                 fontsize=8, color=GREY)
        pdf.savefig(fig)
        plt.close(fig)

        # Page 2: charts
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.text(0.05, 0.94, f"Performance detail, {month.strftime('%B %Y')}", fontsize=16, fontweight="bold", color=NAVY)
        boxes = [(0.05, 0.47, 0.9, 0.44), (0.05, 0.03, 0.43, 0.42), (0.52, 0.03, 0.43, 0.42)]
        for png, box in zip(charts, boxes):
            ax = fig.add_axes(box)
            ax.imshow(plt.imread(BytesIO(png)))
            ax.axis("off")
        pdf.savefig(fig)
        plt.close(fig)


# --------------------------------------------------------------------------
# 6. Main
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate the OPSPULSE monthly ITSM report.")
    parser.add_argument("--month", help="Reporting month as YYYY-MM (default: latest month in the data)")
    args = parser.parse_args()

    df = load_incidents(DB_FILE)
    month = pd.Period(args.month, "M") if args.month else df["month"].max()
    if month not in set(df["month"]):
        raise SystemExit(f"No incidents found for {month}. Available: {df['month'].min()} to {df['month'].max()}")
    prev_month = month - 1
    month_end = month.end_time.floor("s")

    cur = df[df["month"] == month]
    prev = df[df["month"] == prev_month]
    ytd = df[df["month"] <= month]

    kc, kp, ky = kpis(cur), kpis(prev), kpis(ytd)
    kc["Open incidents"] = len(open_backlog(df, month_end))  # open at month end, from any month
    rows = []
    for name in kc:
        c, p = kc[name], kp[name]
        if name == "SLA compliance":
            change = (c - p) * 100 if p == p else None  # percentage points
        else:
            change = (c - p) / p if p else None
        rows.append({"Metric": name, "This month": c, "Previous month": p, "Change": change,
                     "Year to date": ky[name]})
    kpi_table = pd.DataFrame(rows)
    kpi_table.loc[kpi_table["Metric"] == "Open incidents", ["Previous month", "Change", "Year to date"]] = None

    by_priority = performance_by(cur, "priority")
    by_group = performance_by(cur, "assignment_group").sort_values("Breaches", ascending=False)
    trend = monthly_trend(df, month)
    backlog = open_backlog(df, month_end)
    breaches = cur[cur["sla_met"] == 0][["incident_id", "opened_at", "resolved_at", "priority",
                                         "sla_target_hours", "resolution_hours", "assignment_group",
                                         "assigned_to", "category"]].copy()
    breaches["Hours over target"] = (breaches["resolution_hours"] - breaches["sla_target_hours"]).round(2)
    breaches = breaches.sort_values("Hours over target", ascending=False)
    find = findings(cur, prev, by_group, by_priority, backlog, month, prev_month)

    charts = [chart_trend(trend, month), chart_priority(by_priority, month), chart_groups(by_group, month)]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUT_DIR / f"OPSPULSE_ITSM_Report_{month}"
    build_excel(base.with_suffix(".xlsx"), month, kpi_table, find, trend, by_priority, by_group,
                backlog, breaches, charts)
    build_pdf(base.with_suffix(".pdf"), month, kc, kp, find, charts)

    print(f"OPSPULSE report for {month.strftime('%B %Y')}")
    print(f"  Incidents {kc['Total incidents']}  |  SLA {kc['SLA compliance']:.1%}  |  "
          f"Breaches {kc['SLA breaches']}  |  Open at month end {kc['Open incidents']}")
    for st, area, text in find.itertuples(index=False):
        print(f"  [{st}] {area}: {text}")
    print(f"Saved: {base.with_suffix('.xlsx')}")
    print(f"Saved: {base.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()
