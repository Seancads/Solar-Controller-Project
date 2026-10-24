"""Invented history for the Analytics page's "Simulated" data source.

Lets you see what the page looks like before a real device has logged weeks
of data. Switch the Analytics page to "Logged" to see real data instead.
"""

import math
import random
from datetime import datetime, timedelta

ANALYTICS_DAYS = 30
RATED_PANEL_WATTS = 50          # only used to turn average power into an efficiency %

_cache = {"day": None, "data": None}


def generate_daily_history(num_days=ANALYTICS_DAYS):
    """One synthetic summary record per day, ending today.

    A fixed random seed keeps the numbers the same between restarts, which
    makes demos and screenshots repeatable."""
    rng = random.Random(42)
    days = []
    for i in range(num_days - 1, -1, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        # Most days are sunny; some are cloudy with clearly lower output.
        is_cloudy = rng.random() < 0.2
        peak_power_w = rng.uniform(18, 30) if is_cloudy else rng.uniform(32, 46)
        avg_power_w = peak_power_w * rng.uniform(0.5, 0.7)
        sunlight_hours = rng.uniform(4, 6) if is_cloudy else rng.uniform(7, 10)
        days.append({
            "date": date,
            "peak_power_w": round(peak_power_w, 1),
            "avg_power_w": round(avg_power_w, 1),
            "total_energy_wh": round(avg_power_w * sunlight_hours, 1),
            "avg_voltage": round(rng.uniform(16.5, 19.5), 2),
            "sunlight_hours": round(sunlight_hours, 1),
            "efficiency_pct": round(avg_power_w / RATED_PANEL_WATTS * 100, 1),
            "partial": False,
        })
    return days


def get_daily_history():
    """Cached per calendar day, so dates roll forward after midnight."""
    today = datetime.now().strftime("%Y-%m-%d")
    if _cache["day"] != today:
        _cache["data"] = generate_daily_history()
        _cache["day"] = today
    return _cache["data"]


def generate_hourly_profile(days):
    """Average power by hour of day: half a sine wave between 6 AM and 6 PM,
    scaled by the selected days' average peak power."""
    avg_peak = sum(d["peak_power_w"] for d in days) / len(days)
    rng = random.Random(7)
    profile = []
    for hour in range(24):
        shape = math.sin(math.pi * (hour - 6) / 12) if 6 <= hour <= 18 else 0
        profile.append({"hour": hour,
                        "avg_power_w": round(avg_peak * 0.9 * shape * rng.uniform(0.95, 1.05), 1)})
    return profile
