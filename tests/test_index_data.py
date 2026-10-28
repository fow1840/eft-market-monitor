import pandas as pd
import pytest
from src.index_data import validate_index,update_index


def frame():
    return pd.DataFrame(dict(date=pd.bdate_range('2024-01-01',periods=5),open=10,high=11,low=9,close=10,volume=100))


def test_index_validation_and_cache(tmp_path):
    path=tmp_path/'market.db'
    r=update_index(path,'沪深300',fetcher=lambda x:frame())
    assert r['rows']==5
    update_index(path,'沪深300',fetcher=lambda x:frame())
    import sqlite3
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM index_quotes').fetchone()[0]==5


def test_index_corrupt_duplicate_and_future():
    for col,value in [('date','2099-01-01'),('low',20),('volume',float('nan'))]:
        f=frame();f.loc[0,col]=value
        with pytest.raises(ValueError):validate_index(f)
    with pytest.raises(ValueError):validate_index(pd.concat([frame(),frame()]))
