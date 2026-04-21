import os
import time
import requests
from prometheus_client import start_http_server, Gauge

# --- Config from environment variables ---
API_KEY    = os.getenv("OWM_API_KEY", "c4c584af5e82aa764b28e7c93bd4e11f")
CITY       = os.getenv("OWM_CITY", "Madrid")
INTERVAL   = int(os.getenv("OWM_INTERVAL", "60"))   # seconds between scrapes
PORT       = int(os.getenv("OWM_PORT", "9877"))
BASE_URL   = "https://api.openweathermap.org/data/2.5/weather"

# --- Prometheus metrics ---
LABELS = ["city", "country"]

temperature   = Gauge("weather_temperature_celsius",    "Temperature in Celsius",            LABELS)
feels_like    = Gauge("weather_feels_like_celsius",     "Feels like temperature in Celsius", LABELS)
humidity      = Gauge("weather_humidity_percent",       "Humidity in percent",               LABELS)
pressure      = Gauge("weather_pressure_hpa",           "Atmospheric pressure in hPa",       LABELS)
wind_speed    = Gauge("weather_wind_speed_ms",          "Wind speed in m/s",                 LABELS)
wind_deg      = Gauge("weather_wind_direction_degrees", "Wind direction in degrees",         LABELS)
cloudiness    = Gauge("weather_cloudiness_percent",     "Cloudiness in percent",             LABELS)
visibility_m  = Gauge("weather_visibility_meters",      "Visibility in meters",              LABELS)


def fetch_and_update():
    params = {"q": CITY, "appid": API_KEY, "units": "metric"}
    try:
        resp = requests.get(BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        city    = data["name"]
        country = data["sys"]["country"]
        labels  = [city, country]

        temperature.labels(*labels).set(data["main"]["temp"])
        feels_like.labels(*labels).set(data["main"]["feels_like"])
        humidity.labels(*labels).set(data["main"]["humidity"])
        pressure.labels(*labels).set(data["main"]["pressure"])
        wind_speed.labels(*labels).set(data["wind"]["speed"])
        wind_deg.labels(*labels).set(data["wind"].get("deg", 0))
        cloudiness.labels(*labels).set(data["clouds"]["all"])
        visibility_m.labels(*labels).set(data.get("visibility", 0))

        print(f"[OK] {city}, {country} — {data['main']['temp']}°C, humidity {data['main']['humidity']}%")
    except Exception as e:
        print(f"[ERROR] Could not fetch weather data: {e}")


if __name__ == "__main__":
    print(f"Starting OpenWeatherMap exporter on port {PORT} for city: {CITY}")
    start_http_server(PORT)
    while True:
        fetch_and_update()
        time.sleep(INTERVAL)
