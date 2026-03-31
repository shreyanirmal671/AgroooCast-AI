import pandas as pd
import numpy as np
import joblib
import os

from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
from lightgbm import LGBMRegressor


MODEL_PATH = "models/climate_model.pkl"


# ==============================
# FEATURE ENGINEERING
# ==============================

def create_features(df: pd.DataFrame):

    df = df.copy()

    df["datetime"] = pd.to_datetime(df["datetime"])

    df["hour"] = df["datetime"].dt.hour
    df["day"] = df["datetime"].dt.day
    df["month"] = df["datetime"].dt.month

    return df


# ==============================
# TRAIN MODEL
# ==============================

def train_model(dataset_path="datasets/weather_history.csv"):

    df = pd.read_csv(dataset_path)

    df = create_features(df)

    features = [
        "humidity",
        "wind_speed",
        "precip_prob",
        "solar_rad",
        "hour",
        "day",
        "month"
    ]

    target = "temp"

    X = df[features]
    y = df[target]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42
    )

    model = LGBMRegressor(
        n_estimators=400,
        learning_rate=0.05,
        max_depth=8
    )

    model.fit(X_train, y_train)

    preds = model.predict(X_test)

    rmse = np.sqrt(mean_squared_error(y_test, preds))
    r2 = r2_score(y_test, preds)

    os.makedirs("models", exist_ok=True)

    joblib.dump(model, MODEL_PATH)

    return {
        "rmse": rmse,
        "r2": r2
    }


# ==============================
# LOAD MODEL
# ==============================

def load_model():

    if not os.path.exists(MODEL_PATH):

        print("Model not found. Training new model...")

        train_model()

    model = joblib.load(MODEL_PATH)

    return model


# ==============================
# SAFE FEATURE PREPARATION
# ==============================

def ensure_required_features(df):

    defaults = {
        "humidity": 60,
        "wind_speed": 3,
        "precip_prob": 0.1,
        "solar_rad": 200
    }

    for col in defaults:

        if col not in df.columns:
            df[col] = defaults[col]

    return df


# ==============================
# PREDICT FUTURE WEATHER
# ==============================

def predict_weather(model, weather_df: pd.DataFrame):

    df = weather_df.copy()

    df = create_features(df)

    df = ensure_required_features(df)

    features = [
        "humidity",
        "wind_speed",
        "precip_prob",
        "solar_rad",
        "hour",
        "day",
        "month"
    ]

    X = df[features]

    predictions = model.predict(X)

    df["predicted_temp"] = predictions
    df["predicted_humidity"] = df["humidity"]
    df["predicted_precip"] = df["precip_prob"]

    return df


# ==============================
# FARM MICROCLIMATE PREDICTION
# ==============================

def predict_farm_microclimate(weather_df, satellite_data):

    model = load_model()

    prediction_df = predict_weather(model, weather_df)

    if satellite_data:

        ndvi = satellite_data.get("NDVI", 0.5)

        # adjust prediction using vegetation health
        prediction_df["predicted_temp"] = (
            prediction_df["predicted_temp"] * (1 - ndvi * 0.1)
        )

    return prediction_df




# ==============================
# RUN TRAINING FROM TERMINAL
# ==============================

if __name__ == "__main__":

    print("Training climate prediction model...")

    results = train_model()

    print("Model trained successfully!")

    print(f"RMSE: {results['rmse']}")
    print(f"R2 Score: {results['r2']}")

    print("Model saved at: models/climate_model.pkl")