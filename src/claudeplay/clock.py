'''date and time tools built into the gateway, read from this machine's clock and time zone'''

from datetime import datetime, timezone

from fastmcp import FastMCP

NAME = 'clock'


def format_timestamp(now: datetime) -> dict:
    ''' a local datetime in every form the timestamp tool returns '''
    offset = now.utcoffset()
    if offset is None:
        utc_offset = ''
        utc = ''
    else:
        minutes = int(offset.total_seconds() // 60)
        sign = '+' if minutes >= 0 else '-'
        utc_offset = f'{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}'
        utc = now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    time_12h = f'{now.hour % 12 or 12}:{now:%M %p}'
    human_date = f'{now:%A %B} {now.day}, {now.year}'
    iso_year, iso_week, _ = now.isocalendar()
    return {
        'iso': now.isoformat(timespec='seconds'),
        'utc': utc,
        'unix': int(now.timestamp()),
        'date': now.strftime('%Y-%m-%d'),
        'time': now.strftime('%H:%M:%S'),
        'time_12h': time_12h,
        'day_of_week': now.strftime('%A'),
        'human_date': human_date,
        'human': f'{human_date} at {time_12h}',
        'iso_week': f'{iso_year}-W{iso_week:02d}',
        'timezone': now.tzname() or '',
        'utc_offset': utc_offset,
    }


def get_current_timestamp() -> dict:
    ''' the current local date and time in every common form, with this machine's offset from utc '''
    return format_timestamp(datetime.now().astimezone())


def server() -> FastMCP:
    clock = FastMCP(NAME)
    clock.tool(get_current_timestamp)
    return clock
