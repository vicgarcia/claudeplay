'''date and time tools built into the gateway, read from this machine's clock and time zone'''

from datetime import datetime

from fastmcp import FastMCP

NAME = 'clock'


def get_current_timestamp() -> dict:
    ''' today's date in every form, and the current time to the second with this machine's offset from utc '''
    now = datetime.now().astimezone()
    return {
        'date': now.strftime('%Y-%m-%d'),
        'day_of_week': now.strftime('%A'),
        'month': now.strftime('%B'),
        'day': now.day,
        'year': now.year,
        'timestamp': now.isoformat(timespec='seconds'),
        'timezone': now.tzname(),
    }


def server() -> FastMCP:
    clock = FastMCP(NAME)
    clock.tool(get_current_timestamp)
    return clock
