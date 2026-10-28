"""AppTest verifies real local cached data paths without network access."""
from datetime import date
from pathlib import Path
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from src.market_data import save_quotes
from src.history import save_portfolio, save_snapshot

ROOT = Path(__file__).resolve().parents[1]
PAGES = ['app.py', 'pages/1_今日市场.py', 'pages/2_ETF观察.py',
         'pages/3_市场宽度.py', 'pages/4_我的组合.py', 'pages/5_历史记录.py']


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    path = tmp_path / 'market.db'
    monkeypatch.setenv('ETF_DB_PATH', str(path))
    monkeypatch.setenv('ETF_LOG_PATH', str(tmp_path / 'market.log'))
    def forbidden(*args, **kwargs):
        raise AssertionError('Page rerender must not access network')
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)
    return path


@pytest.mark.parametrize('page', PAGES)
def test_pages_start_without_data_or_network(local_data, page):
    app = AppTest.from_file(ROOT / page).run(timeout=15)
    assert not app.exception
    assert app.title


def test_etf_page_uses_cached_indicators(local_data):
    n = 300
    close = pd.Series(range(100, 100 + n), dtype=float)
    frame = pd.DataFrame(dict(date=pd.bdate_range('2023-01-02', periods=n),
        open=close, high=close + 1, low=close - 1, close=close,
        volume=1000.0, amount=100000.0))
    save_quotes(local_data, '510300', frame, 'test fixture')
    app = AppTest.from_file(ROOT / 'pages/2_ETF观察.py').run(timeout=15)
    assert not app.exception
    assert any(metric.value == '强' for metric in app.metric)
    assert len(app.dataframe[0].value) == n
    assert 'ma60' in app.dataframe[0].value.columns


def test_dashboard_portfolio_and_missing_market_guard(local_data):
    save_portfolio(local_data, [dict(name='科技', amount=1500, category='科技', target_pct=5),
        dict(name='现金', amount=8500, category='现金/短债', target_pct=95)])
    app = AppTest.from_file(ROOT / 'app.py').run(timeout=15)
    assert not app.exception
    assert any('数据不完整' in warning.value for warning in app.warning)
    advice = app.dataframe[1].value
    tech = advice[advice.category == '科技'].iloc[0]
    assert tech['建议'] == '建议再平衡'
    assert '禁止继续加仓' in tech['原因']


def test_history_reads_local_snapshots(local_data):
    save_snapshot(local_data, date.today().isoformat(), {'market': {'state': '中性'}})
    app = AppTest.from_file(ROOT / 'pages/5_历史记录.py').run(timeout=15)
    assert not app.exception
    assert len(app.expander) == 1
    assert app.json
