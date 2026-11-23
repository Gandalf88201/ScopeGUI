import re
from math import isfinite
from scope import constants


def search_string(string: str, lines: list, typ: str='all', lowlim: int=None, uplim: int=None, debug: int=0):
    #if type(lines) != list: lines = list([lines])
    if debug > 0: print(f"SEARCH STRING: searching {string} in file")
    list_of_results = []
    for lx, line in enumerate(lines):
        if string in line:
            if debug > 0: print(f"SEARCH STRING: found string in line {lx}")
            if lowlim and uplim:
                if lx >= lowlim and lx <= uplim: list_of_results.append(lx)  
            elif lowlim and not uplim:
                if lx >= lowlim: list_of_results.append(lx)  
            elif uplim and not lowlim:
                if lx <= uplim: list_of_results.append(lx)  
            elif not lowlim and not uplim:
                list_of_results.append(lx)  
    if len(list_of_results) > 0:
        if typ.lower() == 'all': return list(list_of_results), True
        elif typ.lower() == 'first': return list_of_results[0], True
        elif typ.lower() == 'last': return list_of_results[-1], True
        else: print("Incorrect variable 'typ' in search_string call")
    else: return [], False


def parse_time(value: str | int | float, output_unit: str='seconds', *, input_unit: str='seconds') -> float:
    """Reads a nonnegative elapsed time and returns its value in the requested unit.

    Bare numbers use input_unit. Both input_unit and output_unit default to seconds.
    Units include fs, ps, ns, µs, ms, seconds, minutes, hours, days, weeks and
    years (365.25 days). The result retains fractional units.

    Accepts labelled quantities ('1h30m', '2 days, 4.5 seconds'), clocks (MM:SS,
    HH:MM:SS, D:HH:MM:SS or D-HH[:MM[:SS]]), day-prefixed clocks
    ('2 days, 03:04:05') and ISO 8601 week, day and time forms ('P2W',
    'P2DT3H4M5.5S'). Calendar months require a reference date and are unsupported.
    Raises ValueError for an invalid elapsed time or unit.
    """
    text         = str(value).strip().casefold()
    input_scale  = constants._seconds_per_unit(input_unit)
    output_scale = constants._seconds_per_unit(output_unit)
    number       = r'(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?'

    if re.fullmatch(number,text):
        seconds = float(text)*input_scale

    elif ':' in text or re.match(r'\d+-',text):
        day_prefix = r'(?:(\d+)(?:-|\s+(?:days?,?\s+)?))?'
        clock = re.fullmatch(day_prefix + r'(\d+(?::\d+){0,3}(?:[.,]\d+)?)',text)
        if clock is None: raise ValueError(f'Invalid elapsed time: {value!r}')
        days, clock_time = clock.groups()
        fields = clock_time.replace(',','.').split(':')
        # Day-prefixed clocks start with hours. Other clocks end with seconds.
        weights = (3600,60,1)
        if days is None: weights = (86400,3600,60,1)[-len(fields):]
        elif len(fields) > 3: raise ValueError(f'Invalid elapsed time: {value!r}')
        seconds = float(days or 0)*86400 + sum(float(field)*weight for field,weight in zip(fields,weights))

    elif text.startswith('p'):
        amount    = r'(\d+(?:[.,]\d+)?)'
        days_part = rf'(?:{amount}d)?'
        time_part = rf'(?:{amount}h)?(?:{amount}m)?(?:{amount}s)?'
        iso       = re.fullmatch(rf'p(?:{amount}w|{days_part}(?:t{time_part})?)',text)
        if iso is None or text == 'p' or text.endswith('t'): raise ValueError(f'Invalid elapsed time: {value!r}')
        seconds = 0
        for field,unit in zip(iso.groups(),'wdhms'):
            if field is not None: seconds += float(field.replace(',','.'))*constants.TIME_UNITS[unit]

    else:
        seconds = 0
        end     = 0
        for term in re.finditer(rf'({number})\s*([a-zμ]+)',text):
            separator = text[end:term.start()].strip()
            allowed   = ('',',','and',', and') if end else ('',)
            if separator not in allowed: raise ValueError(f'Invalid elapsed time: {value!r}')
            seconds += float(term[1])*constants._seconds_per_unit(term[2])
            end = term.end()
        if end == 0 or text[end:] not in ('','.'): raise ValueError(f'Invalid elapsed time: {value!r}')

    result = seconds/output_scale
    if not isfinite(result): raise ValueError(f'Elapsed time is too large: {value!r}')
    return result
