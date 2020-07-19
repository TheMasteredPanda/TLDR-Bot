import re
import math

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
        if val == 0:
            return
        if len(ret) >= accuracy:
            return
        ret.append(f'{val} {long}')

    round_toward_zero = math.floor if sec > 0 else math.ceil
    parsed = {
        'days': round_toward_zero(sec / 86400),
        'hours': round_toward_zero(sec / 3600) % 24,
        'minutes': round_toward_zero(sec / 60) % 60,
        'seconds': round_toward_zero(sec / 1) % 60
    }
    add(math.trunc(parsed['days'] / 365), plural(math.trunc(sec / 365), y, "year"))
    add(parsed['days'] % 365, plural(sec, d, "day"))
    add(parsed['hours'], plural(sec, h, "hour"))
    add(parsed['minutes'], plural(sec, m, "minute"))
    add(parsed['seconds'], plural(sec, 1, "second"))
    return ' '.join(ret)


def plural(sec, n, name):
    sec_abs = abs(sec)
    is_plural = (sec_abs >= (n * 1.5))
    plr = f'{name}s' if is_plural else f'{name}'
    return plr


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
        n = int(match[0])
        ptype = match[1] if match[1] else 's'
        switcher = {
            'years': n * y,
            'year': n * y,
            'yrs': n * y,
            'yr': n * y,
            'y': n * y,
            'weeks': n * w,
            'week': n * w,
            'w': n * w,
            'days': n * d,
            'day': n * d,
            'd': n * d,
            'hours': n * h,
            'hour': n * h,
            'hrs': n * h,
            'hr': n * h,
            'h': n * h,
            'minutes': n * m,
            'minute': n * m,
            'mins': n * m,
            'min': n * m,
            'm': n * m,
            'seconds': n,
            'second': n,
            'secs': n,
            'sec': n,
            's': n
        }
        tm += switcher.get(ptype, 0)
    return tm