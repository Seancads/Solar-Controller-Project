"""Checking a reading from the ESP32 before it is accepted (Hardware Acquisition module).

One bad sample can wreck a day's peak and average, so impossible values are
rejected rather than stored.
"""


def _number(value, name):
    if value is None or isinstance(value, bool):
        raise ValueError("%s is required and must be a number." % name)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number." % name)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("%s must be a finite number." % name)
    return number


def validate_reading(voltage, current, power=None):
    """Return clean (voltage, current, power) floats or raise ValueError.

    Rejects impossible values rather than storing them, because one bad
    sample can wreck a day's peak/average."""
    v = _number(voltage, "voltage")
    i = _number(current, "current")
    if not 0 <= v <= 100:
        raise ValueError("voltage must be between 0 and 100 V.")
    if not -0.5 <= i <= 50:
        raise ValueError("current must be between 0 and 50 A.")
    if i < 0:
        i = 0.0                       # tiny negative = sensor offset noise
    if power is None:
        p = v * i
    else:
        p = _number(power, "power")
        if not 0 <= p <= 5000:
            raise ValueError("power must be between 0 and 5000 W.")
    return v, i, round(p, 3)
