from datetime import datetime, timedelta, timezone

from claudeplay import clock


class Frozen(datetime):
    ''' 11:59:58 pm on a sunday, 5 hours behind utc '''

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 1, 23, 59, 58, 123456, tzinfo=tz)

    def astimezone(self, tz=None):
        return self.replace(tzinfo=timezone(timedelta(hours=-5), 'Eastern Standard Time'))


def test_timestamp_has_every_part_of_the_date_and_the_time_to_the_second(monkeypatch):
    monkeypatch.setattr(clock, 'datetime', Frozen)
    assert clock.get_current_timestamp() == {
        'date': '2026-11-01',
        'day_of_week': 'Sunday',
        'month': 'November',
        'day': 1,
        'year': 2026,
        'timestamp': '2026-11-01T23:59:58-05:00',
        'timezone': 'Eastern Standard Time',
    }
