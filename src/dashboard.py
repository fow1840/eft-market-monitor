"""Read-only dashboard assembly; render never triggers network calls."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from src.market_data import read_quotes
from src.indicators import summarize_indicators
from src.history import latest_observation
from src.signals import market_state


def build_dashboard(path, symbol='510300'):
    today=datetime.now(ZoneInfo('Asia/Shanghai')).date()
    quotes=read_quotes(path,symbol)
    warnings=[]
    summary=summarize_indicators(quotes) if not quotes.empty else {}
    stale=quotes.empty or (today-quotes.date.iloc[-1].date()).days>4
    trend={'state':summary.get('trend','数据不足'),**summary}
    volume={'state':summary.get('volume_state','数据不足'),'volume_ratio':summary.get('volume_ratio'),'date':summary.get('date'),'source':summary.get('source')}
    if stale:
        trend['state']=volume['state']='数据不足'
        warnings.append('行情缺失或超过4个日历日未更新；不产生方向判断')
    observations={}
    for kind,key,max_age in [('shares',symbol,4),('valuation','沪深300',45),('breadth','market',4)]:
        item=latest_observation(path,kind,key) or {'available':False,'state':None,'reasons':['本地尚无数据']}
        if item.get('date') and (today-datetime.fromisoformat(item['date']).date()).days>max_age:
            item={**item,'state':None,'available':False}
            warnings.append(f'{kind} 数据过期')
        observations[kind]=item
    dimensions={'trend':trend['state'],'volume':volume['state'],**{k:v.get('state') for k,v in observations.items()}}
    market=market_state(dimensions)
    if not market['complete']:warnings.append('五维数据不足；中性仅为占位，不代表风险低')
    return dict(date=str(today),symbol=symbol,trend=trend,volume=volume,market=market,quotes=quotes,warnings=warnings,**observations)
