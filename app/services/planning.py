from datetime import date, timedelta


def week_start(d: date) -> date:
    """The Monday of d's week."""
    return d - timedelta(days=d.weekday())
