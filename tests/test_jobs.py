from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from jobs.update import schedule_ready,retry


def test_schedule_timezone_and_weekend():
    tz=ZoneInfo('Asia/Shanghai')
    assert not schedule_ready('close',datetime(2024,1,2,15,29,tzinfo=tz))
    assert schedule_ready('close',datetime(2024,1,2,15,30,tzinfo=tz))
    assert schedule_ready('shares',datetime(2024,1,2,8,45,tzinfo=tz))
    assert not schedule_ready('shares',datetime(2024,1,6,12,tzinfo=tz))
    with pytest.raises(ValueError):schedule_ready('close',datetime(2024,1,2))


def test_bounded_retry():
    calls=[]
    def fails():calls.append(1);raise ConnectionError()
    with pytest.raises(ConnectionError):retry(fails)
    assert len(calls)==2
