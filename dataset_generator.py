import pandas as pd
import numpy as np
import os

np.random.seed(42)

# Generate hourly timestamps
date_range = pd.date_range(
    start="2020-01-01",
    end="2025-01-01",
    freq="h"
)

rows = len(date_range)

df = pd.DataFrame()
df["datetime"] = date_range

# Extract time features
df["hour"] = df["datetime"].dt.hour
df["day_of_year"] = df["datetime"].dt.dayofyear

# Seasonal temperature pattern
seasonal_temp = 10 * np.sin(2 * np.pi * df["day_of_year"] / 365)

# Daily temperature cycle
daily_temp = 6 * np.sin(2 * np.pi * df["hour"] / 24)

# Base temperature
df["temp"] = 22 + seasonal_temp + daily_temp + np.random.normal(0, 1.5, rows)

# Humidity inversely related to temperature
df["humidity"] = 80 - (df["temp"] * 1.5) + np.random.normal(0, 5, rows)
df["humidity"] = np.clip(df["humidity"], 30, 100)

# Wind speed random but realistic
df["wind_speed"] = np.random.uniform(0.5, 10, rows)

# Rain probability related to humidity
df["precip_prob"] = df["humidity"] / 100 + np.random.normal(0, 0.05, rows)
df["precip_prob"] = np.clip(df["precip_prob"], 0, 1)

# Solar radiation depends on daytime
df["solar_rad"] = np.where(
    (df["hour"] > 6) & (df["hour"] < 18),
    np.random.normal(500, 120, rows),
    0
)

df["solar_rad"] = np.clip(df["solar_rad"], 0, None)

# Keep only required columns
df = df[[
    "datetime",
    "temp",
    "humidity",
    "wind_speed",
    "precip_prob",
    "solar_rad"
]]

os.makedirs("datasets", exist_ok=True)

df.to_csv("datasets/weather_history.csv", index=False)

print("Realistic dataset generated")
print("Rows:", len(df))