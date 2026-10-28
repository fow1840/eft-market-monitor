from pathlib import Path
import hashlib
import sqlite3
import pandas as pd
import pytest
from jobs.backtest_report import read_cached_prices, build_report, render_markdown


def cached():
    return pd.DataFrame({'date': pd.bdate_range('2020-01-01', periods=40),
                         'open': 10., 'close': 10., 'source': 'test', 'fetched_at': '2020-03-01'})


def test_database_read_only_and_missing_not_created(tmp_path):
    missing = tmp_path / 'missing.db'
    with pytest.raises(ValueError): read_cached_prices(missing)
    assert not missing.exists()
    db_path = tmp_path / 'quotes.db'
    frame = cached(); frame['symbol'] = '510300'
    frame['date'] = frame.date.dt.strftime('%Y-%m-%d')
    with sqlite3.connect(db_path) as db:
        frame.to_sql('quotes', db, index=False)
    digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert len(read_cached_prices(db_path)) == 40
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == digest


def test_report_is_actual_data_with_risk_explicitly_unavailable():
    report = build_report(cached())
    assert report['rows'] == 40
    assert set(report['metrics']) == {'hold', 'dca'}
    assert report['calendar_validation']['status'] == '未验证'
    assert report['metrics']['hold']['total_return'] < 0  # fees, no price change
    markdown = render_markdown(report)
    assert '未复权' in markdown and '不可用' in markdown


def test_explicit_calendar_checks_gaps_instead_of_filling():
    frame = cached()
    calendar = frame[['date']].copy()
    report = build_report(frame, calendar=calendar)
    assert report['calendar_validation']['status'] == '通过'
    with pytest.raises(ValueError):
        build_report(frame.drop(index=3), calendar=calendar)


def test_reject_duplicate_or_missing_price():
    frame = cached()
    frame.loc[4, 'close'] = None
    with pytest.raises(ValueError): build_report(frame)
    with pytest.raises(ValueError): build_report(pd.concat([cached(), cached().iloc[:1]]))
