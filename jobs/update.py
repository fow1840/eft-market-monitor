"""Manual/scheduled local updates. python -m jobs.update close|shares [--force]."""
import argparse
from datetime import datetime, timedelta
import json
import sys
from zoneinfo import ZoneInfo
from config import load_settings
from src.logging_setup import configure_logging
from src.market_data import ETF_UNIVERSE, update_quotes
from src.history import save_observation, latest_observation, save_snapshot, load_portfolio
from src.dashboard import build_dashboard


def schedule_ready(job, now=None):
    if job not in ('close','shares'):raise ValueError('unknown job')
    now=now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is None:raise ValueError('timezone-aware timestamp required')
    now=now.astimezone(ZoneInfo('Asia/Shanghai'))
    hour,minute=(15,30) if job=='close' else (8,45)
    return now.weekday()<5 and (now.hour,now.minute)>=(hour,minute)


def retry(call, attempts=2):
    import time
    if not isinstance(attempts,int) or not 1 <= attempts <= 3:
        raise ValueError('attempts must be 1..3')
    for i in range(attempts):
        try:return call()
        except Exception:
            if i+1==attempts:raise
            time.sleep(.5)


def run_update(job, force=False):
    if job not in ('close','shares'):raise ValueError('unknown job')
    from src.fundamentals import fetch_shares,fetch_shares_history,analyze_shares,fetch_valuation,analyze_valuation,fetch_breadth
    from src.calendar import load_calendar
    from src.index_data import update_index
    import pandas as pd
    settings=load_settings(); logger=configure_logging(settings.log_path,settings.log_level)
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    if not force and not schedule_ready(job,now):
        return {'skipped':True,'reason':'未到上海工作日计划时间'}
    outcomes={}
    def record(name,call):
        try:outcomes[name]=call();logger.info('update %s succeeded',name)
        except Exception as exc:
            outcomes[name]={'error':type(exc).__name__}
            logger.error('update %s failed: %s',name,type(exc).__name__)
    if job=='close':
        for symbol in ETF_UNIVERSE:
            def quote(symbol=symbol):
                r=update_quotes(settings.db_path,symbol,force=force,retries=2)
                return {'rows':len(r['data']),'error':r['error'],'source':r['source']}
            record(symbol,quote)
        for index in ('沪深300','A500','科创50','创业板'):
            record('index_'+index,lambda index=index:retry(lambda:update_index(settings.db_path,index)))
        for index in ('沪深300','A500','科创50','创业板'):
            def valuation(index=index):
                try:
                    data=retry(lambda:fetch_valuation(index)); r=analyze_valuation(data,source='中证指数官方PE1')
                except Exception as exc:
                    r={'available':False,'state':None,'source':'中证指数官方','reasons':[type(exc).__name__]}
                if r.get('state') is None:
                    from src.valuation_fallback import fetch_valuation_fallback
                    alternative=fetch_valuation_fallback(index)
                    if alternative.get('state') is not None:
                        alternative['official_fields']=r
                        r=alternative
                    else:
                        r['fallback_reasons']=alternative.get('reasons',[])
                if r.get('date'):save_observation(settings.db_path,'valuation',index,r['date'],r)
                return r
            record(index,valuation)
        def breadth():
            r=retry(fetch_breadth)
            if r.get('date'):save_observation(settings.db_path,'breadth','market',r['date'],r)
            return r
        record('breadth',breadth)
    else:
        # Previous calendar date; a non-trading date legitimately yields no record.
        calendar=load_calendar()
        usable=calendar[calendar.date<now.date()]
        day=str(usable[-1].date())
        for symbol in ETF_UNIVERSE:
            def shares(symbol=symbol):
                from src.history import query_observations
                old=query_observations(settings.db_path,'shares_raw',symbol)
                data=retry(lambda:fetch_shares_history(symbol,day,trading_calendar=calendar)) if len(old)<21 else retry(lambda:fetch_shares(symbol,day))
                new=data[['date','shares']].copy()
                if old:
                    previous=pd.DataFrame([{'date':x['date'],'shares':x['shares']} for x in old])
                    new=pd.concat([previous,new])
                    new['date']=pd.to_datetime(new['date'])
                    new=new.drop_duplicates('date',keep='last')
                for row in data.to_dict('records'):
                    save_observation(settings.db_path,'shares_raw',symbol,str(pd.Timestamp(row['date']).date()),{'shares':float(row['shares'])})
                r=analyze_shares(new,source='上交所官方',trading_calendar=calendar)
                if r.get('date'):save_observation(settings.db_path,'shares',symbol,r['date'],r)
                return r
            record(symbol,shares)
    dashboard=build_dashboard(settings.db_path)
    snapshot={k:v for k,v in dashboard.items() if k!='quotes'}
    snapshot['created_at']=now.isoformat()
    snapshot['update_job']=job
    snapshot['quotes']=dashboard['quotes'].tail(1).assign(date=lambda x:x.date.astype(str)).to_dict('records')
    snapshot['portfolio']=load_portfolio(settings.db_path)
    from src.portfolio import analyze_portfolio,risk_advice
    snapshot['recommendations']=[]
    if snapshot['portfolio']:
        portfolio=analyze_portfolio(snapshot['portfolio'])
        for row in portfolio['categories'].to_dict('records'):
            snapshot['recommendations'].append({'category':row['category'],**risk_advice(row['current_pct'],row['target_pct'],dashboard['market']['state'] if dashboard['market']['complete'] else '数据不足')})
    # Convert unavailable numeric observations to null, never JSON NaN.
    snapshot=json.loads(json.dumps(snapshot,default=str,ensure_ascii=False), parse_constant=lambda _: None)
    save_snapshot(settings.db_path,str(now.date()),snapshot)
    return outcomes


def main():
    parser=argparse.ArgumentParser();parser.add_argument('job',choices=['close','shares']);parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    result=run_update(args.job,args.force)
    print(json.dumps(result,ensure_ascii=False,default=str,allow_nan=False))
    return 1 if any(isinstance(x,dict) and x.get('error') for x in result.values()) else 0

if __name__=='__main__':sys.exit(main())
