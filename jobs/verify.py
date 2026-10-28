"""Read-only local acceptance report; never requests network or accesses secrets."""
from datetime import date
from pathlib import Path
import json
from config import load_settings
from src.market_data import ETF_UNIVERSE, read_quotes
from src.dashboard import build_dashboard
from src.history import query_snapshots


def verify():
    path=load_settings().db_path
    report={'database_exists':path.is_file(),'quotes':{},'dashboard':{},'history_count':0}
    for symbol,name in ETF_UNIVERSE.items():
        data=read_quotes(path,symbol)
        report['quotes'][symbol]={'name':name,'rows':len(data),'latest':str(data.date.max().date()) if len(data) else None,'minimum250':len(data)>=250}
    dashboard=build_dashboard(path)
    report['dashboard']={k:v for k,v in dashboard.items() if k not in ('quotes','trend','volume')}
    report['history_count']=len(query_snapshots(path,'2018-01-01',str(date.today())))
    return report

if __name__=='__main__':
    print(json.dumps(verify(),ensure_ascii=False,indent=2,default=str,allow_nan=False))
