from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_rebalance_page_empty_upload(tmp_path,monkeypatch):
    monkeypatch.setenv('ETF_DB_PATH',str(tmp_path/'market.db'))
    monkeypatch.setenv('ETF_LOG_PATH',str(tmp_path/'market.log'))
    page=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages/7_持仓再平衡.py').run(timeout=20)
    assert not page.exception
    assert len(page.number_input)==2


def workbook_bytes(confirmed=False):
    import openpyxl
    from io import BytesIO
    workbook=openpyxl.Workbook();hold=workbook.active;hold.title='当前持仓'
    hold.append(['账户','基金名称','当前金额(元)','资产桶','可赎回'])
    hold.append(['示例账户','示例宽基',100,'核心宽基','是' if confirmed else None])
    hold.append(['示例账户','示例主题',900,'卫星主题','是' if confirmed else None])
    target=workbook.create_sheet('目标组合')
    target.append(['资产桶','目标比例（可编辑）']);target.append(['核心宽基',.7]);target.append(['卫星主题',.3])
    output=BytesIO();workbook.save(output);return output.getvalue()


def test_upload_shows_two_funded_simulations(tmp_path,monkeypatch):
    import streamlit as st
    from types import SimpleNamespace
    raw=workbook_bytes()
    monkeypatch.setattr(st,'file_uploader',lambda *a,**k:SimpleNamespace(size=len(raw),getvalue=lambda:raw))
    monkeypatch.setenv('ETF_DB_PATH',str(tmp_path/'market.db'))
    monkeypatch.setenv('ETF_LOG_PATH',str(tmp_path/'market.log'))
    page=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages/7_持仓再平衡.py').run(timeout=20)
    assert not page.exception
    assert not page.error
    funds=page.dataframe[1].value
    assert funds['本轮资金平衡计划额(元)'].tolist()==[150.,-150.]
    assert funds['已确认条件下本轮金额(元)'].tolist()==[0.,0.]
    assert len(page.tabs)==2


def test_confirmed_upload_shows_budgeted_buys(tmp_path,monkeypatch):
    import streamlit as st
    from types import SimpleNamespace
    raw=workbook_bytes(True)
    monkeypatch.setattr(st,'file_uploader',lambda *a,**k:SimpleNamespace(size=len(raw),getvalue=lambda:raw))
    monkeypatch.setenv('ETF_DB_PATH',str(tmp_path/'market.db'))
    monkeypatch.setenv('ETF_LOG_PATH',str(tmp_path/'market.log'))
    page=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages/7_持仓再平衡.py').run(timeout=20)
    assert not page.exception and not page.error
    funds=page.dataframe[1].value
    assert funds['已确认条件下本轮金额(元)'].tolist()==[150.,-150.]


def test_download_neutralizes_formulas_but_keeps_negative_money():
    import pandas as pd
    from io import BytesIO
    from src.export_utils import safe_excel_csv
    frame=pd.DataFrame({'name':['=HYPERLINK("example")','  +formula','普通名称'],'amount':[-150.,25.,0.]})
    restored=pd.read_csv(BytesIO(safe_excel_csv(frame)))
    assert restored.name.iloc[0].startswith("'=")
    assert restored.name.iloc[1].startswith("'  +")
    assert restored.amount.tolist()==[-150.,25.,0.]
