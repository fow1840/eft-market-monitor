"""Manual, bounded, public-data index update probe."""
from config import load_settings
from src.index_data import update_index
from src.fundamentals import INDEX_CODES

if __name__=='__main__':
    for index in INDEX_CODES:
        try:print(index,update_index(load_settings().db_path,index),flush=True)
        except Exception as exc:print(index,type(exc).__name__,flush=True)
