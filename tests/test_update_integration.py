from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from config import Settings
from jobs import update
from src.history import query_snapshots


def test_source_failures_do_not_prevent_snapshot(tmp_path,monkeypatch):
    path=tmp_path/'local.db'
    monkeypatch.setattr(update,'load_settings',lambda:Settings(path,tmp_path/'app.log','INFO'))
    monkeypatch.setattr(update,'ETF_UNIVERSE',{'510300':'沪深300'})
    monkeypatch.setattr(update,'retry',lambda fn,**kwargs:fn())
    monkeypatch.setattr(update,'update_quotes',lambda *a,**k:{'data':pd.DataFrame(),'error':'offline','source':None})
    def unavailable(*a,**k):raise ConnectionError('offline')
    monkeypatch.setattr('src.index_data.update_index',unavailable)
    monkeypatch.setattr('src.fundamentals.fetch_valuation',unavailable)
    monkeypatch.setattr('src.fundamentals.fetch_breadth',unavailable)
    monkeypatch.setattr('src.valuation_fallback.fetch_valuation_fallback',lambda *a,**k:{'available':False,'state':None,'reasons':['offline']})
    result=update.run_update('close',force=True)
    assert result['510300']['error']=='offline'
    assert result['breadth']['error']=='ConnectionError'
    rows=query_snapshots(path,'2000-01-01','2099-01-01')
    assert len(rows)==1
    assert rows[0]['payload']['market']['complete'] is False
    assert rows[0]['payload']['portfolio']==[]


def test_schedule_skip_has_no_network_or_snapshot(tmp_path,monkeypatch):
    path=tmp_path/'local.db'
    monkeypatch.setattr(update,'load_settings',lambda:Settings(path,tmp_path/'app.log','INFO'))
    monkeypatch.setattr(update,'schedule_ready',lambda *a:False)
    result=update.run_update('close')
    assert result['skipped'] is True
    assert not path.exists()
