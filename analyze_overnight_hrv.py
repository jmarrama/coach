#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["garmin-fit-sdk>=21"]
# ///
"""Inspect HRV FIT files and compare the unweighted sample mean with Garmin's summary."""
import argparse
from pathlib import Path
from statistics import mean

from garmin_fit_sdk import Decoder, Stream


def inspect(path, reported):
    data, errors = Decoder(Stream.from_file(str(path))).read()
    if errors:
        raise ValueError(f'{path}: FIT decoding errors: {errors}')
    samples = [m for m in data.get('hrv_value_mesgs', [])
               if isinstance(m.get('value'), (float, int))]
    summaries = data.get('hrv_status_summary_mesgs', [])
    if not samples and not summaries:
        return False
    print(f'\n{path}')
    if samples:
        values = [x['value'] for x in samples]
        times = sorted(x['timestamp'] for x in samples if x.get('timestamp') is not None)
        avg = mean(values)
        print(f'  {len(values)} HRV readings; arithmetic mean {avg:.2f} ms')
        if times:
            print(f'  Time range: {times[0]} to {times[-1]}')
        if reported is not None:
            print(f'  User-reported Garmin average: {reported:g} ms; difference {avg-reported:+.2f} ms')
        if len(summaries) == 1 and summaries[0].get('last_night_average') is not None:
            ref = summaries[0]['last_night_average']
            print(f'  FIT last-night average: {ref:.2f} ms; difference {avg-ref:+.2f} ms')
        elif len(summaries) > 1:
            print('  Multiple summaries present; compare only after matching the correct sleep period.')
    else:
        print('  No individual HRV readings in this file.')
    for item in summaries:
        print(f"  FIT summary at {item.get('timestamp')}: nightly={item.get('last_night_average')} ms, weekly={item.get('weekly_average')} ms")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', type=Path, help='FIT files or directories to search recursively')
    parser.add_argument('--reported', type=float, help='Known Garmin nightly average in ms, for a single FIT file')
    args = parser.parse_args()
    files = []
    for path in args.paths:
        if path.is_dir():
            files.extend(p for p in path.rglob('*') if p.is_file() and p.suffix.lower() == '.fit')
        elif path.is_file():
            files.append(path)
        else:
            parser.error(f'Path does not exist: {path}')
    if args.reported is not None and len(files) != 1:
        parser.error('--reported requires exactly one FIT file')
    found = failures = 0
    for path in sorted(set(files)):
        try:
            found += inspect(path, args.reported)
        except (ValueError, OSError, RuntimeError) as error:
            failures += 1
            print(f'Error: {error}')
    print(f'\nScanned {len(set(files))} FIT files; {found} contained HRV samples or summaries; {failures} failed.')
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
