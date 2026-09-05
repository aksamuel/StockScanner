"""User-facing New York timestamps, with minute precision and a 24-hour clock."""
from datetime import datetime
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def format_new_york_time(moment=None):
    moment = moment or datetime.now(NEW_YORK)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=NEW_YORK)
    return moment.astimezone(NEW_YORK).strftime("%d/%b/%Y, %H:%M %Z")
