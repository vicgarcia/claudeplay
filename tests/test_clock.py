from datetime import datetime, timedelta, timezone

from claudeplay import clock


class Frozen(datetime):
    ''' 11:59:58 pm on a sunday, 5 hours behind utc '''

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 1, 23, 59, 58, 123456, tzinfo=tz)

    def astimezone(self, tz=None):
        if tz is not None:
            return datetime.astimezone(self, tz)
        return self.replace(tzinfo=timezone(timedelta(hours=-5), 'Eastern Standard Time'))


def test_timestamp_has_every_field(monkeypatch):
    monkeypatch.setattr(clock, 'datetime', Frozen)
    assert clock.get_current_timestamp() == {
        'iso': '2026-11-01T23:59:58-05:00',
        'utc': '2026-11-02T04:59:58Z',
        'unix': 1793595598,
        'date': '2026-11-01',
        'time': '23:59:58',
        'time_12h': '11:59 PM',
        'day_of_week': 'Sunday',
        'human_date': 'Sunday November 1, 2026',
        'human': 'Sunday November 1, 2026 at 11:59 PM',
        'iso_week': '2026-W44',
        'timezone': 'Eastern Standard Time',
        'utc_offset': '-05:00',
    }


def test_offsets_ahead_of_utc_and_by_half_hours_are_signed():
    ahead = datetime(2026, 1, 5, 0, 30, tzinfo=timezone(timedelta(hours=5, minutes=30), 'IST'))
    stamp = clock.format_timestamp(ahead)
    assert stamp['utc_offset'] == '+05:30'
    assert stamp['utc'] == '2026-01-04T19:00:00Z'
    assert stamp['time_12h'] == '12:30 AM'
    behind = datetime(2026, 1, 5, 12, 0, tzinfo=timezone(timedelta(hours=-3, minutes=-30), 'NST'))
    assert clock.format_timestamp(behind)['utc_offset'] == '-03:30'


def test_a_naive_time_has_no_utc_parts():
    stamp = clock.format_timestamp(datetime(2026, 1, 5, 9, 0))
    assert stamp['utc'] == '' and stamp['utc_offset'] == '' and stamp['timezone'] == ''
