from datetime import date
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile
import openpyxl
import pytest
from src.holdings_excel import parse_holdings_excel


def workbook(rows=None,targets=None,extra_headers=()):
    w=openpyxl.Workbook();s=w.active;s.title='当前持仓'
    s.append(['账户','基金名称','当前金额(元)','资产桶','重复/重叠组',*extra_headers])
    for row in rows or [['示例账户','示例宽基','1,000.25','核心宽基','宽基重叠']]:s.append(row)
    t=w.create_sheet('目标组合');t.append(['资产桶','目标占比',None,None,None,None,None,None,'目标比例（可编辑）'])
    for i,(bucket,value) in enumerate(targets or [('核心宽基',1)],start=2):t.append([bucket,f'=I{i}',None,None,None,None,None,None,value])
    b=BytesIO();w.save(b);return b.getvalue()


def test_existing_ledger_layout_prefers_editable_target_and_unknown_restrictions():
    r=parse_holdings_excel(workbook())
    assert r['targets']=={'核心宽基':Decimal('1')}
    assert r['holdings'][0]['amount']==Decimal('1000.25')
    assert r['holdings'][0]['holding_status']=='unknown'
    assert r['metadata']['formulas_evaluated'] is False
    assert any('人工确认' in w for w in r['warnings'])


def test_duplicate_names_keep_separate_rows_and_ids():
    r=parse_holdings_excel(workbook(rows=[['A','示例基金',100,'核心宽基','同基金'],['B','示例基金',200,'核心宽基','同基金']]))
    assert len(r['holdings'])==2
    assert len({x['id'] for x in r['holdings']})==2
    assert sum(x['amount'] for x in r['holdings'])==300
    assert any('同名' in x for x in r['warnings'])

@pytest.mark.parametrize('value',[-1,float('inf'),'abc','25%','=1+1','1.001'])
def test_bad_amount_rejected(value):
    with pytest.raises(ValueError):parse_holdings_excel(workbook(rows=[['A','示例',value,'核心宽基','']]))

@pytest.mark.parametrize('targets',[[('核心宽基',.9)],[('核心宽基',-1)],[('核心宽基',100)],[('核心宽基',.5),('核心宽基',.5)]])
def test_bad_targets_rejected(targets):
    with pytest.raises(ValueError):parse_holdings_excel(workbook(targets=targets))


def test_percentage_targets_and_stream():
    r=parse_holdings_excel(BytesIO(workbook(targets=[('核心宽基','75%'),('现金/短债','25%')])))
    assert r['targets']['现金/短债']==Decimal('.25')

@pytest.mark.parametrize('redeem,restriction,earliest,expected',[
    ('是','','2024-01-01','free'),('否','','2024-01-01','locked'),('是','','2028-01-01','locked'),
    ('是','一年持有期','','unknown'),('','','2024-01-01','unknown'),('','','bad','unknown'),('','无','','free')])
def test_restrictions_no_guessing(redeem,restriction,earliest,expected):
    payload=workbook(rows=[['A','示例',100,'核心宽基','',redeem,restriction,earliest]],extra_headers=['可赎回','赎回限制','最早赎回日'])
    r=parse_holdings_excel(payload,today=date(2026,10,28))
    assert r['holdings'][0]['holding_status']==expected


def test_no_worksheet_dimensions_supported():
    raw=workbook();out=BytesIO()
    import re
    with ZipFile(BytesIO(raw)) as z,ZipFile(out,'w') as target:
        for item in z.infolist():
            value=z.read(item.filename)
            if item.filename.startswith('xl/worksheets/'):
                value=re.sub(rb'<dimension[^>]*/>',b'',value)
            target.writestr(item,value)
    assert parse_holdings_excel(out.getvalue())['metadata']['holding_rows']==1


def test_missing_sheets_invalid_zip_and_size_limits(monkeypatch):
    with pytest.raises(ValueError):parse_holdings_excel(b'not excel')
    monkeypatch.setattr('src.holdings_excel.MAX_UPLOAD_BYTES',10)
    with pytest.raises(ValueError):parse_holdings_excel(workbook())


def test_rows_limit(monkeypatch):
    monkeypatch.setattr('src.holdings_excel.MAX_ROWS',2)
    with pytest.raises(ValueError):parse_holdings_excel(workbook(rows=[['A','a',1,'核心宽基',''],['A','b',1,'核心宽基','']]))


def test_sparse_rows_outside_limit_are_not_silently_ignored():
    raw=workbook();out=BytesIO()
    with ZipFile(BytesIO(raw)) as source,ZipFile(out,'w') as target:
        for item in source.infolist():
            payload=source.read(item.filename)
            if item.filename=='xl/worksheets/sheet1.xml':
                payload=payload.replace(b'</sheetData>',b'<row r="9000"><c r="A9000" t="inlineStr"><is><t>hidden</t></is></c></row></sheetData>')
            target.writestr(item,payload)
    with pytest.raises(ValueError,match='行数'):parse_holdings_excel(out.getvalue())


def test_enormous_numeric_amount_rejected_as_validation_error():
    with pytest.raises(ValueError):parse_holdings_excel(workbook(rows=[['A','example','1e99','核心宽基','']]))


def test_explicit_holding_period_restriction_overrides_redeem_yes():
    payload=workbook(rows=[['A','example',100,'核心宽基','','是','未满持有期']],extra_headers=['可赎回','持有期'])
    r=parse_holdings_excel(payload)
    assert r['holdings'][0]['holding_status']=='locked'


def test_explicit_fund_target_fraction():
    payload=workbook(rows=[['A','example',100,'核心宽基','','100%']],extra_headers=['目标仓位'])
    assert parse_holdings_excel(payload)['holdings'][0]['fund_target']==Decimal('1')


def test_malformed_sheet_xml_is_validation_error():
    raw=workbook();out=BytesIO()
    with ZipFile(BytesIO(raw)) as source,ZipFile(out,'w') as target:
        for item in source.infolist():
            payload=source.read(item.filename)
            if item.filename=='xl/worksheets/sheet1.xml':payload=b'<broken'
            target.writestr(item,payload)
    with pytest.raises(ValueError):parse_holdings_excel(out.getvalue())


def test_sparse_columns_outside_limit_are_not_silently_ignored():
    raw=workbook();out=BytesIO()
    with ZipFile(BytesIO(raw)) as source,ZipFile(out,'w') as target:
        for item in source.infolist():
            payload=source.read(item.filename)
            if item.filename=='xl/worksheets/sheet1.xml':
                payload=payload.replace(b'</sheetData>',b'<row r="4"><c r="ZZ4" t="inlineStr"><is><t>hidden</t></is></c></row></sheetData>')
            target.writestr(item,payload)
    with pytest.raises(ValueError,match='列数'):parse_holdings_excel(out.getvalue())
