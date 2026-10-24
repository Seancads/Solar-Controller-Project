"""Small date helpers shared by several modules. Times use the computer's local time zone."""

from datetime import datetime


def start_of_day(ts):
    """Local midnight at the start of the day containing `ts`, as a datetime."""
    return datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0)
