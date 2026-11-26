import pandas as pd

df = pd.read_csv("data/raw/incidents_raw.csv")

print(df.shape)
print(df.dtypes)
print(df.isna().sum())
print(df.head())