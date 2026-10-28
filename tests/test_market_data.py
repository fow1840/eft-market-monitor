import pandas as pd
import pytest
from src.market_data import validate_quotes, update_quotes, read_quotes


def sample(n=260):
    return pd.DataFrame({'date':pd.bdate_range('2024-01-01', periods=n),
       'open':10.,'high':11.,'low':9.,'close':10.,'volume':100.,'amount':1000.})


def test_validation_dedup_and_order():
    frame=sample()
    result=validate_quotes(pd.concat([frame.iloc[::-1],frame.iloc[:1]]))
    assert len(result)==260 and result.date.is_monotonic_increasing

@pytest.mark.parametrize('col,value', [('close',float('nan')),('high',5),('volume',-1),('amount',float('inf')),('date','2099-01-01')])
def test_invalid_rejected(col,value):
    frame=sample(); frame.loc[0,col]=value
    with pytest.raises(ValueError): validate_quotes(frame)


def test_conflicting_duplicate():
    frame=sample(); extra=frame.iloc[:1].copy(); extra['volume']=5
    with pytest.raises(ValueError): validate_quotes(pd.concat([frame,extra]))


def test_retry_cache_and_fallback(tmp_path):
    calls=[]
    def fetch(symbol,provider):
        calls.append(provider)
        if provider=='eastmoney': raise ConnectionError('offline')
        return sample()
    path=tmp_path/'quotes.db'
    result=update_quotes(path,'510300',fetcher=fetch)
    assert calls==['eastmoney','eastmoney','sina']
    assert len(result['data'])==260 and result['source']=='sina'
    update_quotes(path,'510300',fetcher=lambda *a,**k:pytest.fail('must use cache'))
    assert len(read_quotes(path,'510300'))==260
    result=update_quotes(path,'510300',force=True,fetcher=lambda *a,**k: (_ for _ in ()).throw(ConnectionError()))
    assert result['error'] and len(result['data'])==260


def test_short_history_not_saved(tmp_path):
    result=update_quotes(tmp_path/'q.db','510300',fetcher=lambda *a,**k:sample(10),retries=1)
    assert result['data'].empty and result['error']
