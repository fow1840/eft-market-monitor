from pathlib import Path
import hashlib
import sqlite3
import numpy as np
import pandas as pd
import pytest
from jobs.strategy_report import (additional_metrics,build_comparison,conclusion_text,
    load_public_data,passive_sleeve,allocation_reference,render_markdown,write_artifacts,NAMES)
from src.strategies import load_config


def configuration():
    config=load_config()
    config['windows'].update(short=2,medium=4,long=8,volume=2,pullback=3)
    return config


def prices(n=100):
    close=100+np.arange(n)*.1+np.sin(np.arange(n)/4)
    return pd.DataFrame({'date':pd.bdate_range('2019-10-01',periods=n),
        'open':close,'high':close+1,'low':close-1,'close':close,'volume':1000.,'source':'synthetic unit fixture'})


def test_underwater_and_losing_streak_include_unfinished_drawdown():
    frame=pd.DataFrame({'date':pd.bdate_range('2020-01-01',periods=7),
                       'equity':[100.,90.,80.,100.,95.,94.,93.]})
    result=additional_metrics(frame,100)
    assert result['max_underwater_sessions']==3
    assert result['max_losing_streak_sessions']==3
    with pytest.raises(ValueError):additional_metrics(frame.assign(equity=0),100)


def test_initial_sleeve_is_not_daily_rebalancing():
    frame=pd.DataFrame({'date':pd.bdate_range('2020-01-01',periods=3),'open':[10.,20.,10.],'close':[10.,20.,10.]})
    result=passive_sleeve(frame,.5,initial_capital=100,fee_rate=0)
    assert result.daily.equity.tolist()==[100,150,100]
    assert result.daily.trades.sum()==1
    assert result.daily.units.nunique()==1
    costly=passive_sleeve(frame,.5,initial_capital=100,fee_rate=.01)
    assert costly.metrics['fees']==pytest.approx(50-50/1.01)


def test_report_all_four_rows_missing_fundamentals_are_not_curves():
    result=build_comparison({'510300':prices(),'159665':prices()},start='2020-01-01',end='2020-02-14',config=configuration())
    table=result['comparison'].set_index('name')
    assert table.loc[NAMES['A'],'status']=='历史数据不足'
    assert table.loc[NAMES['C'],'status']=='历史数据不足'
    assert NAMES['A'] not in result['curves'] and NAMES['C'] not in result['curves']
    assert NAMES['B'] in result['curves']
    assert NAMES['D']+' 159665' in result['curves']
    assert any('初始10%' in name for name in result['curves'])
    assert any('每日恒定60%' in name for name in result['curves'])
    assert '建议保留简单策略' in result['conclusion']
    assert {'fees','fee_impact_return_pp','max_underwater_sessions','max_losing_streak_sessions'}<=set(table)
    assert set(result['stability'].partition)>={'前70%','后30%','2020'}


def test_invalid_publication_history_cannot_be_reported_as_valid():
    frame=prices()
    frame['pe_percentile']=.2;frame['pb_percentile']=.2;frame['breadth_ratio']=.7
    frame['valuation_available_at']='2050-01-01'
    frame['breadth_available_at']='2050-01-01'
    result=build_comparison({'510300':frame},start='2020-01-01',config=configuration())
    for strategy in ('A','C'):
        assert NAMES[strategy] not in result['curves']
        assert result['comparison'].set_index('name').loc[NAMES[strategy],'status']=='历史数据不足'


def test_future_suffix_does_not_change_historical_comparison():
    original=prices();modified=original.copy()
    cutoff=pd.Timestamp('2020-01-24')
    modified.loc[modified.date>cutoff,'close']*=2
    modified.loc[modified.date>cutoff,'open']*=2
    left=build_comparison({'510300':original},start='2020-01-01',end=str(cutoff.date()),config=configuration())
    right=build_comparison({'510300':modified},start='2020-01-01',end=str(cutoff.date()),config=configuration())
    pd.testing.assert_frame_equal(left['comparison'],right['comparison'])
    for key in left['curves']:pd.testing.assert_frame_equal(left['curves'][key],right['curves'][key])


def test_artifacts_are_standalone_and_explain_comparisons(tmp_path):
    result=build_comparison({'510300':prices()},start='2020-01-01',config=configuration(),dca_months=6)
    output=tmp_path/'assets';report=tmp_path/'STRATEGY_REPORT.md'
    write_artifacts(result,output,report)
    assert (output/'comparison.csv').is_file()
    assert (output/'stability.csv').is_file()
    assert (output/'decisions.csv').is_file()
    html=(output/'nav_drawdown.html').read_text()
    assert 'plotly.js' in html and 'cdn.plot.ly' not in html[:500]
    text=report.read_text()
    assert '每日恒定' in text and '最长水下交易日' in text and '不构成未来20%' in text
    assert '分6个月' in text
    assert result['decisions'].reasons.notna().all()


def test_cache_reader_never_creates_or_modifies_database(tmp_path):
    missing=tmp_path/'missing.db'
    with pytest.raises(ValueError):load_public_data(missing)
    assert not missing.exists()
    path=tmp_path/'market.db';data=prices(10);data['symbol']='510300'
    with sqlite3.connect(path) as db:data.to_sql('quotes',db,index=False)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    frames,index=load_public_data(path)
    assert len(frames['510300'])==10 and index.empty
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest


def test_candidate_criterion_is_configurable_and_not_a_guarantee():
    table=pd.DataFrame([dict(name=NAMES['B'],status='可计算',max_drawdown=-.1,annual_return=.08,max_underwater_sessions=100,annual_return_dispersion=.1),
        dict(name='简单初始60%风险仓持有',status='可计算',max_drawdown=-.25,annual_return=.08,max_underwater_sessions=200,annual_return_dispersion=.2)])
    stability=pd.DataFrame([dict(name=name,partition=str(year),max_drawdown=drawdown)
        for name,drawdown in [(NAMES['B'],-.1),('简单初始60%风险仓持有',-.25)] for year in (2020,2021)])
    assert '待样本外复核的候选' in conclusion_text(table,stability)
    assert '建议保留简单策略' in conclusion_text(table,stability,{'drawdown_improvement':.2})


def test_references_never_fill_zero_volume_bars():
    frame=pd.DataFrame({'date':pd.bdate_range('2020-01-01',periods=4),
        'open':[10.,20.,30.,15.],'close':[10.,20.,30.,15.],'volume':[0.,0.,100.,0.]})
    passive=passive_sleeve(frame,.5,initial_capital=100,fee_rate=0)
    constant=allocation_reference(frame,.5,initial_capital=100,fee_rate=0,rebalance=True)
    for result in (passive,constant):
        assert result.daily.trades.tolist()==[0,0,1,0]
        assert result.daily.units.iloc[0]==0
        assert result.daily.units.iloc[2]==pytest.approx(50/30)
        assert result.daily.units.iloc[3]==result.daily.units.iloc[2]
