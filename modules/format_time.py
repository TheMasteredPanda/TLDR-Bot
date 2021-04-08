import re
import math

s = 1
m = 60
h = m * 60
d = h * 24
w = d * 7
y = d * 365.25


def seconds(sec: int, *, accuracy: int = 2):
    """
    Converts seconds into human readable time, eg. 2 days 5 hours 35 minutes 16 seconds

    Parameters
    ___________
    sec: :class:`int`
        The amount of seconds to convert.
    accuracy: :class:`int`
        How deep to go into the human readable time, starts from the biggest
        eg. accuracy of 2 => 2 days 5 hours
            accuracy of 4 => 2 days 5 hours 35 minutes 16 seconds

    Returns
    -------
    :class:`str`
        Time in human readable format.
    """
    if sec < 60:
        return f'{sec} seconds'

    ret = []

    def add(val, long):
        if val == 0 or len(ret) >= accuracy:
            return
        long += 's' if val > 1 else ''
        ret.append(f'{val} {long}')

    round_toward_zero = math.floor if sec > 0 else math.ceil
    parsed = {
        'days': round_toward_zero(sec / 86400),
        'hours': round_toward_zero(sec / 3600) % 24,
        'minutes': round_toward_zero(sec / 60) % 60,
        'seconds': round_toward_zero(sec / 1) % 60
    }
    add(math.trunc(parsed['days'] / 365), "year")
    add(parsed['days'] % 365, "day")
    add(parsed['hours'], "hour")
    add(parsed['minutes'], "minute")
    add(parsed['seconds'], "second")
    return ' '.join(ret)


def parse(string: str = None, return_string: bool = False):
    """
    Converts time from human readable format to seconds.

    Parameters
    ___________
    string: :class:`str`
        The human readable time string.
    return_string :class:`bool`
        Whether to return string after extracting time or not.

    Returns
    -------
    :class:`int`
        Time in seconds.
    Optional[:class:`int`]
        String after extracting time from it
    """
    if string is None:
        return None

    time_total = 0

    regex = re.compile(r'^(\d+\s?(?:seconds?|secs?|sec?|s|minutes?|mins?|min?|m|hours?|hrs?|hr?|h|days?|d|weeks?|w|years?|yrs?|yr?|y)(?:\s|$))')
    while True:
        match = re.findall(regex, string)
        if not match:
            break

        # remove match from string, so if needed string without time can be returned
        string = string.replace(match[0], '').strip()

        # get number from match
        num = int(re.findall('^\d+', match[0])[0])
        # get type from match (h, m, s etc etc)
        time_type = re.findall('[a-zA-Z]', match[0])[0]

        try:
            time_total += num * globals()[time_type[0]]
        except KeyError:
            continue

    if return_string:
        return time_total, string.strip()

    return time_total
