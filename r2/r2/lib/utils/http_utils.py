import pytz
from datetime import datetime

DATE_RFC822 = '%a, %d %b %Y %H:%M:%S %Z'
DATE_RFC850 = '%A, %d-%b-%y %H:%M:%S %Z'
DATE_ANSI = '%a %b %d %H:%M:%S %Y'

def read_http_date(date_str):
    try:
        date = datetime.strptime(date_str, DATE_RFC822)
    except ValueError:
        try:
            date = datetime.strptime(date_str, DATE_RFC850)
        except ValueError:
            date = datetime.strptime(date_str, DATE_ANSI)
    date = date.replace(tzinfo = pytz.timezone('GMT'))
    return date

def http_date_str(date):
    date = date.astimezone(pytz.timezone('GMT'))
    return date.strftime(DATE_RFC822)
