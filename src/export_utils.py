"""Prevent uploaded text from becoming formulas when a CSV is opened in Excel."""

def safe_excel_csv(frame):
    def escape(value):
        if isinstance(value,str) and (value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n'))):
            return "'"+value
        return value
    return frame.map(escape).to_csv(index=False).encode('utf-8-sig')
