"""Clean the raw ITSM incident data.

Input : data/raw/incidents_raw.csv
Output: data/processed/incidents_clean.csv
Run from the project root:  python src/clean_data.py
"""
import pandas as pd

# 1. Load the raw data
df = pd.read_csv("data/raw/incidents_raw.csv")
print("Rows before:", len(df))

# 2. Remove exact duplicate rows (a repeated ticket would double-count in reports)
df = df.drop_duplicates()
print("Rows after:", len(df))

# 3. Standardise priority labels: "p1", "P1 ", "Priority 1" -> "P1"
df["priority"] = df["priority"].str.strip().str.upper()
df["priority"] = df["priority"].str.replace("PRIORITY ", "P")
print(df["priority"].value_counts())

# 4. Convert text to real dates. Two formats exist in resolved_at, so try both.
df["opened_at"] = pd.to_datetime(df["opened_at"])
iso = pd.to_datetime(df["resolved_at"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
uk = pd.to_datetime(df["resolved_at"], format="%d/%m/%Y %H:%M", errors="coerce")
df["resolved_at"] = iso.fillna(uk)
print("Open tickets (no resolve date):", df["resolved_at"].isna().sum())

# 5. Fill blanks with a clear label instead of leaving them empty
df["assignment_group"] = df["assignment_group"].fillna("Unassigned")
df["caller_department"] = df["caller_department"].fillna("Unknown")

# 6. Flag impossible rows: resolved BEFORE opened. We keep them but mark them,
#    so later analytics can exclude them instead of silently losing data.
df["bad_dates"] = df["resolved_at"] < df["opened_at"]
print("Tickets resolved before opened:", df["bad_dates"].sum())

# 7. Add useful calculated columns (only for valid, resolved tickets)
valid = df["resolved_at"].notna() & ~df["bad_dates"]
df["resolution_hours"] = ((df["resolved_at"] - df["opened_at"]).dt.total_seconds() / 3600).where(valid).round(2)
df["sla_met"] = (df["resolution_hours"] <= df["sla_target_hours"]).where(valid)

# 8. Save the cleaned data
df.to_csv("data/processed/incidents_clean.csv", index=False)
print("Saved", len(df), "rows to data/processed/incidents_clean.csv")
