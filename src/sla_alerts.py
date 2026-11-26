"""SLA alerts: which open tickets need action right now, before they breach?

Replays any moment in the data ("as of"), scores every ticket open at that moment with the SLA risk table,
and writes an email-ready alert for the service-desk lead. Nothing is sent: the message is saved as a file
you can paste into Outlook or Teams.

Usage (from the project root):
  python src/sla_alerts.py                            # default moment: 3 Sep 2026, 14:00
  python src/sla_alerts.py --as-of "2026-10-13 16:00"

Output: reports/alerts/sla_alert_<YYYY-MM-DD_HHMM>.txt   (email-ready message)
        reports/alerts/open_tickets_<YYYY-MM-DD_HHMM>.csv (every open ticket with risk and status)
"""
import argparse
from pathlib import Path

import pandas as pd

from opspulse_ai import OpsPulseAI

OUT_DIR = Path("reports/alerts")
DEFAULT_AS_OF = "2026-09-03 14:00"


def build_message(as_of, o):
    alerts = o[o["status"] == "Alert"]
    ok = o[o["status"] == "OK"]
    breached = o[o["status"] == "Breached"]
    lines = [
        f"Subject: OPSPULSE SLA alert - {len(alerts)} ticket(s) need action now ({as_of:%d %b %Y %H:%M})",
        "",
        "Hello team,",
        "",
        f"As of {as_of:%d %b %Y %H:%M}, {len(alerts)} open ticket(s) have reached at least 50% breach risk "
        f"and can still be saved:",
        "",
    ]
    if len(alerts):
        for _, r in alerts.iterrows():
            lines.append(f"  - {r['incident_id']} [{r['priority']} | {r['category']}] {r['assignment_group']} / "
                         f"{r['assigned_to']}: {r['hours_left'] * 60:.0f} min left, risk {r['breach_risk']:.0%}")
            lines.append(f"      \"{r['description'][:90]}\"")
            if r["possibly_misrouted"]:
                lines.append(f"      Routing check: this looks like a {r['suggested_team']} ticket; consider reassigning.")
    else:
        lines.append("  - None. Nothing is close to breaching right now.")
    lines += [
        "",
        f"On track: {len(ok)} ticket(s) open and below the alert level.",
        f"Already breached and still open: {len(breached)} (oldest open for "
        f"{breached['hours_open'].max() / 24:.0f} days)." if len(breached) else "Already breached: none.",
        "",
        "Suggested action: pick up the alerted tickets first, ordered by minutes left, and reassign any flagged "
        "by the routing check.",
        "",
        "OPSPULSE (automated, risk table learned from Jan-Aug 2026)",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="List tickets at risk of breaching SLA at a moment in time.")
    parser.add_argument("--as-of", default=DEFAULT_AS_OF, help='e.g. "2026-10-13 16:00"')
    args = parser.parse_args()
    as_of = pd.Timestamp(args.as_of)

    ai = OpsPulseAI()
    o = ai.open_at(as_of)
    msg = build_message(as_of, o)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{as_of:%Y-%m-%d_%H%M}"
    (OUT_DIR / f"sla_alert_{stamp}.txt").write_text(msg, encoding="utf-8")
    o.drop(columns=["sla_met"]).to_csv(OUT_DIR / f"open_tickets_{stamp}.csv", index=False)

    print(msg)
    print(f"\nSaved: {OUT_DIR / f'sla_alert_{stamp}.txt'}")
    print(f"Saved: {OUT_DIR / f'open_tickets_{stamp}.csv'}")


if __name__ == "__main__":
    main()
