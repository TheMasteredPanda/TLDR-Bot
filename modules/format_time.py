import re
import math

s = 1
m = 60
h = m * 60
d = h * 24
w = d * 7
y = d * 365.25


def seconds(sec, *, accuracy=2):
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


def parse(string=None):
    if string is None:
        return None

    if string.isdigit():
        return string

    string_split = string.split(' ')

    def split(s):
        tail = s.rstrip('0123456789')
        head = s[len(tail):]
        return head + tail

    split_str = [split(s) for s in string_split]
    tm = 0
    for i in split_str:
        regex = re.compile(r'^((?:\d+)?\-?\d?\.?\d+) *(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w|years?|yrs?|y)?$')
        match = re.findall(regex, i)
        if not match:
            return None

        match = match[0]
        num = int(match[0])
        time_type = match[1] if match[1] else 's'

        try:
            tm += num * globals()[time_type[0]]
        except:
            continue

    return tm
