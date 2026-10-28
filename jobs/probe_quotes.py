"""Bounded live quote validation. Run python -m jobs.probe_quotes."""
from src.market_data import ETF_UNIVERSE, update_quotes
from config import load_settings

if __name__ == '__main__':
    for symbol in ETF_UNIVERSE:
        result = update_quotes(load_settings().db_path,symbol,retries=1)
        data = result['data']
        print(symbol,len(data),str(data.date.max()) if len(data) else '-',result['source'],result['error'],flush=True)
