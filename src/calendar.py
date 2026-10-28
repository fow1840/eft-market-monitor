"""Published local trading calendar. No weekend interpolation."""
from pathlib import Path
from datetime import timedelta
from zoneinfo import ZoneInfo
import pandas as pd

CALENDAR_PATH=Path(__file__).resolve().parents[1]/'data'/'trading_calendar.csv'


def load_calendar(path=CALENDAR_PATH):
    days=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(path)['date'],errors='raise')).normalize()
    if days.has_duplicates or not days.is_monotonic_increasing or days.empty:
        raise ValueError('invalid trading calendar')
    return days


def latest_completed_session(now, calendar=None):
    if now.tzinfo is None:raise ValueError('aware datetime required')
    now=now.astimezone(ZoneInfo('Asia/Shanghai'))
    days=load_calendar() if calendar is None else pd.DatetimeIndex(calendar)
    if now.date()>days.max().date():return None
    cutoff=now.date() if (now.hour,now.minute)>=(15,30) else now.date()-timedelta(days=1)
    usable=days[days.date<=cutoff]
    return usable[-1].date() if len(usable) else None
