'''date and time tools built into the gateway, read from this machine's clock and time zone'''

from datetime import datetime

from fastmcp import FastMCP

NAME = 'clock'


def get_todays_date() -> dict:
    ''' today's date in this machine's time zone '''
    now = datetime.now()
    return {
        'date': now.strftime('%Y-%m-%d'),
        'day_of_week': now.strftime('%A'),
        'month': now.strftime('%B'),
        'day': now.day,
        'year': now.year,
    }


def get_current_timestamp() -> dict:
    ''' the current time to the second, with this machine's offset from utc '''
    now = datetime.now().astimezone()
    return {
        'timestamp': now.isoformat(timespec='seconds'),
        'timezone': now.tzname(),
    }


def server() -> FastMCP:
    clock = FastMCP(NAME)
    clock.tool(get_todays_date)
    clock.tool(get_current_timestamp)
    return clock
