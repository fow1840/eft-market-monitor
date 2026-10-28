from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from src.calendar import latest_completed_session,load_calendar


def test_actual_calendar_holiday_and_cutoff():
    calendar=load_calendar();tz=ZoneInfo('Asia/Shanghai')
    assert str(latest_completed_session(datetime(2024,10,8,9,tzinfo=tz),calendar))=='2024-09-30'
    assert str(latest_completed_session(datetime(2024,10,8,16,tzinfo=tz),calendar))=='2024-10-08'
    assert latest_completed_session(datetime(2099,1,1,16,tzinfo=tz),calendar) is None
