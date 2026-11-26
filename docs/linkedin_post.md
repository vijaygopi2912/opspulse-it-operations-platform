# LinkedIn post draft

Paste into LinkedIn and attach `reports/demo/opspulse_demo.gif` (or `docs/architecture.png`).

---

I built OPSPULSE, an end-to-end IT service management analytics and AI project, to sharpen my skills in data
engineering, BI and applied AI.

What it does, on 3,000 synthetic incidents:

🔹 Data pipeline: cleans messy ITSM data (duplicates, mixed date formats, bad timestamps) into a SQLite database
🔹 SQL analytics: CTEs and window functions for SLA trends, workload and backlog
🔹 Power BI: a one-page executive dashboard with 52 DAX measures, every number checked against SQL
🔹 Automation: a monthly management report (Excel + PDF) in one command
🔹 AI ticket triage: a free, local semantic model reaches 94.9% category accuracy on wording it has never seen (keyword ML: 60%)
🔹 Similar tickets: suggests the right team 89.2% of the time, better than the original routing, plus the likely fix
🔹 Root cause analysis: grouping tickets by meaning showed the March and August SLA dips hit 25 of 28 problem types at once, pointing to capacity, not one broken system
🔹 SLA early warning: a simple risk table beat machine learning on unseen months (AUC 0.74 vs 0.68), so I shipped the simple one
🔹 A FastAPI service and a small web app to demo it all

Three things I learned:
1. Test on data the model has never seen. My first model scored 100%, then 60% on new wording.
2. Simple often beats complex. Choosing the explainable rule was the right call.
3. Validate everything. A reviewer read a cross-filtered dashboard as wrong numbers, so I added a live filter banner.

Everything runs free on a laptop. Code, dashboard and write-up:
https://github.com/vijaygopi2912/opspulse-it-operations-platform

#ITSM #DataEngineering #PowerBI #SQL #Python #MachineLearning #AIOps #ServiceManagement #DataAnalytics
