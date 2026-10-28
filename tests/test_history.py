import pytest
from src.history import save_snapshot, query_snapshots, save_portfolio, load_portfolio, save_observation, latest_observation


def test_snapshot_range_and_upsert(tmp_path):
    path=tmp_path/'history.db'
    for day in ('2024-01-01','2024-01-02','2024-01-03'):
        save_snapshot(path,day,{'state':'中性'})
    save_snapshot(path,'2024-01-02',{'state':'强'})
    assert query_snapshots(path,'2024-01-02','2024-01-02')==[{'date':'2024-01-02','payload':{'state':'强'}}]
    with pytest.raises(ValueError): query_snapshots(path,'2024-02-01','2024-01-01')
    with pytest.raises(ValueError): save_snapshot(path,'bad',{})
    with pytest.raises(ValueError): save_snapshot(path,'2024-01-01',{'x':float('nan')})


def test_portfolio_local_roundtrip(tmp_path):
    path=tmp_path/'p.db'
    assert load_portfolio(path)==[]
    rows=[dict(name='示例现金',category='现金/短债',amount=100,target_pct=100)]
    save_portfolio(path,rows)
    assert load_portfolio(path)==rows
    with pytest.raises(ValueError): save_portfolio(path,[])
    assert load_portfolio(path)==rows


def test_latest_observation(tmp_path):
    path=tmp_path/'o.db'
    assert latest_observation(path,'breadth') is None
    save_observation(path,'breadth','market','2024-01-02',{'state':'强'})
    save_observation(path,'breadth','market','2024-01-01',{'state':'弱'})
    assert latest_observation(path,'breadth')['state']=='强'
