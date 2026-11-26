# OPSPULSE
### AI-Powered IT Operations Intelligence Platform

**Turning ITSM data into operational intelligence through analytics, automation and AI.**

![Status](https://img.shields.io/badge/Project-In%20Development-orange)
![Python](https://img.shields.io/badge/Python-3.x-blue)
![SQL](https://img.shields.io/badge/SQL-Analytics-lightgrey)
![AI](https://img.shields.io/badge/AI-Integration-purple)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 1. Project Overview

OPSPULSE is a portfolio project focused on building an intelligent IT Operations Management platform.

The platform aims to help IT operations teams analyse incidents, monitor Service Level Agreements (SLAs), identify recurring problems, automate repetitive reporting tasks and use AI to support operational decision-making.

The project simulates an enterprise IT environment and demonstrates how data analytics, Python automation, SQL, APIs and Generative AI can work together to solve real-world ITSM challenges.

## Dashboard preview

![OPSPULSE ITSM executive dashboard](reports/opspulse_executive_dashboard.png)

Single-page Power BI executive dashboard: KPI cards with month-over-month change, monthly volume vs SLA against a 90% target,
department and assignment-group analysis, SLA and resolution performance by priority, and management insights written
automatically by DAX from whatever is selected. Details: [docs/powerbi_dashboard_guide.md](docs/powerbi_dashboard_guide.md).

**Headline results (synthetic data, 3,000 incidents, Jan–Oct 2026)**

| Metric | Value |
|---|---|
| SLA compliance | 88.5% (target 90%) |
| SLA breaches | 326 |
| Weakest priority | P1 at 77.3% SLA |
| Weakest months | March 75.4%, August 77.1% |
| Breach hotspot | Service Desk, 110 breaches (34%) |
| Average resolution | 6.47 hours |

Every dashboard figure was cross-checked against independent SQL queries on the same database.

## 2. Business Problem

Enterprise IT departments handle large volumes of incidents and service requests.

Common operational challenges include:

- Limited visibility into incident trends.
- SLA breaches and delayed resolutions.
- Uneven technician workload.
- Repetitive manual reporting.
- Difficulty identifying recurring incidents.
- Time-consuming incident investigation.
- Fragmented operational information.

OPSPULSE aims to address these challenges through a unified intelligence and automation platform.

## 3. Planned Core Modules

| Module | Purpose |
|---|---|
| Incident Intelligence | Analyse incident volume, categories and trends |
| SLA Monitoring | Identify SLA breaches and potential risks |
| Workforce Analytics | Analyse technician workload and performance |
| Automated Reporting | Generate recurring ITSM reports |
| AI Incident Assistant | Classify and summarise incidents |
| Knowledge Assistant | Retrieve relevant support knowledge |
| Root Cause Intelligence | Identify recurring incident patterns |
| Workflow Automation | Automate repetitive IT operations tasks |

## 4. Technology Stack

**Data Analytics**
- Microsoft Excel
- SQL
- Power BI
- Python
- Pandas

**Automation and Integration**
- Python
- REST APIs
- JSON
- ServiceNow integration concepts

**Artificial Intelligence**
- Large Language Models (LLMs)
- Retrieval-Augmented Generation (RAG)
- AI-assisted classification
- AI workflow automation

**Cloud and Deployment**
- Microsoft Azure fundamentals
- Git and GitHub

## 5. What is built so far

| Stage | Script / file | What it does |
|---|---|---|
| 1. Generate data | `src/generate_data.py` | Creates 3,000 realistic synthetic incidents with deliberate data-quality problems (duplicates, missing values, mixed date formats, inconsistent priority labels) |
| 2. Explore | `src/explore_data.py` | Profiles shape, types and missing values |
| 3. Clean | `src/clean_data.py` | Removes 60 duplicates, standardises priorities, parses both date formats, flags 28 invalid date rows, calculates resolution hours and SLA met/breached |
| 4. Load | `sql/schema.sql`, `src/load_database.py` | Loads a normalised SQLite database (incidents, priorities, assignment groups) |
| 5. Analyse | `sql/analytics_basic.sql`, `sql/analytics_advanced.sql`, `src/run_query.py` | GROUP BY, JOINs, CTEs, window functions (LAG, running totals, RANK, ROW_NUMBER), HAVING |
| 6. Export | `src/export_for_powerbi.py` | Writes the Power BI source workbook |
| 7. Visualise | `reports/opspulse_executive_dashboard_v2.pbix` (+ `.pbip` project) | Power BI data model, date table, 50+ DAX measures, single-page executive dashboard |
| 8. Report | `src/generate_report.py` | One command produces a dated monthly management report: Excel workbook (summary, trend, priority and group performance, open backlog with ticket age, SLA breach list, charts) and a 2-page PDF with traffic-light findings |

### How to run

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash
pip install -r requirements.txt
python src/generate_data.py
python src/clean_data.py
python src/load_database.py
python src/run_query.py sql/analytics_advanced.sql
python src/export_for_powerbi.py
python src/generate_report.py                  # latest month
python src/generate_report.py --month 2026-08  # any month
```

Reports are saved to `reports/output/` as `OPSPULSE_ITSM_Report_<YYYY-MM>.xlsx` and `.pdf`.

Then open `reports/opspulse_executive_dashboard_v2.pbix` in Power BI Desktop.

## 6. Proposed Architecture

```text
        ITSM DATA SOURCES
               |
       Incident / Request Data
               |
               v
       DATA INGESTION LAYER
          Python / APIs
               |
               v
        DATA PROCESSING
       Python / Pandas / SQL
               |
               v
        DATA STORAGE
           SQL DB
               |
          +----+----+
          |         |
          v         v
     ANALYTICS    AI ENGINE
     Power BI     LLM / RAG
          |         |
          v         v
     DASHBOARDS  AI ASSISTANT
          |         |
          +----+----+
               |
               v
       IT OPERATIONS
       INTELLIGENCE
```

*This represents the proposed architecture. Components will be implemented and validated progressively.*

## 7. Development Roadmap

- [x] Incident data foundation
- [x] Data cleaning and validation
- [x] SQL analytics engine
- [x] SLA monitoring
- [x] Power BI dashboard
- [ ] Technician workload analysis
- [x] Incident trend detection
- [x] Automated reporting
- [ ] SLA notification system
- [x] Data pipeline
- [ ] AI incident classification
- [ ] AI ticket summarisation
- [ ] Knowledge-base assistant
- [ ] AI resolution recommendations
- [ ] Root cause analysis
- [ ] REST API integration
- [ ] SLA risk prediction
- [ ] AI operations assistant
- [ ] Platform integration and testing
- [ ] Final demonstration and deployment

## 8. Project Structure

```text
opspulse-it-operations-platform/
│
├── data/
│   ├── raw/            incidents_raw.csv (generated, with data-quality issues)
│   └── processed/      incidents_clean.csv, opspulse.db (SQLite)
├── src/                Python pipeline scripts
├── sql/                schema and analytics queries
├── reports/            Power BI dashboard (.pbix and .pbip project), source workbook, screenshots
├── docs/               dashboard guide, DAX documentation, validation report
├── tests/
│
├── requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

## 9. Data Privacy and Testing

This project uses synthetic ITSM datasets for development and demonstration. Patterns such as the March and August SLA dips
were deliberately built into the generator so the analytics have something real to find; they are not findings about any real organisation.

No confidential employer data, employee information, credentials or private enterprise records will be published.

AI-generated recommendations will be treated as decision support and validated before being considered operationally reliable.

## 10. Project Objective

The objective is to demonstrate practical capabilities in:

- IT Service Management.
- IT Operations Analytics.
- Data Engineering fundamentals.
- Business Intelligence.
- Python Automation.
- API Integrations.
- Generative AI applications.
- Intelligent IT Operations.

## 11. Development Status

**Current status: Phase 1 complete (data pipeline, SQL analytics, Power BI executive dashboard). Automated monthly reporting added. Next: AI incident classification.**

This is an actively developed portfolio project. Features will be marked complete only after implementation and testing.

---

**OPSPULSE — Making IT Operations More Intelligent.**
