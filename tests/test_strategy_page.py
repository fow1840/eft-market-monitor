from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_strategy_page_without_network(tmp_path,monkeypatch):
    monkeypatch.setenv('ETF_DB_PATH',str(tmp_path/'market.db'))
    monkeypatch.setenv('ETF_LOG_PATH',str(tmp_path/'market.log'))
    page=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages/6_策略研究.py').run(timeout=20)
    assert not page.exception
    assert len(page.selectbox)==2
