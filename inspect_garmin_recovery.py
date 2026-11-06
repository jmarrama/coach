#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["garmin-fit-sdk>=21"]
# ///
"""Extract experimental sleep summaries and HRV arrays from a Garmin backup.

Field identities are from Gadgetbridge's reverse-engineered FIT profile:
https://codeberg.org/Freeyourgadget/Gadgetbridge/src/branch/master/FitCodeGenerator/src/main/resources/fit_profile.json
Undocumented fields and HRV array ordering need independent verification.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

DEFAULT = Path(__file__).resolve().parent / 'activities/00020001/GARMIN/FbtBackup/lha_bkup.fit'
EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)


def stamp(value):
    if not isinstance(value, int) or not 0 < value < 0xffffffff:
        return None
    return (EPOCH + timedelta(seconds=value)).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', nargs='?', type=Path, default=DEFAULT)
    args = parser.parse_args()
    messages, errors = Decoder(Stream.from_file(str(args.file))).read()
    if errors:
        raise RuntimeError(f'FIT decoding reported errors: {errors}')
    daily = []
    for item in messages.get('384', []):
        daily.append({'index': item.get(254), 'sleep_start_utc': stamp(item.get(9)),
                      'sleep_end_utc': stamp(item.get(11)), 'start_utc_offset_minutes': item.get(10),
                      'end_utc_offset_minutes': item.get(12), 'minimum_heart_rate_bpm': item.get(0),
                      'sleep_score': item.get(2), 'awake_minutes': item.get(24),
                      'sleep_quality_score': item.get(25)})
    stages = []
    for item in messages.get('411', []):
        stages.append({'index': item.get(254), 'sleep_start_utc': stamp(item.get(10)),
                       'sleep_end_utc': stamp(item.get(8)), 'sleep_score': item.get(0),
                       'deep_minutes': item.get(1), 'light_minutes': item.get(2),
                       'rem_minutes': item.get(3), 'awake_minutes': item.get(4),
                       'unmeasurable_minutes': item.get(5)})
    hrv = []
    for item in messages.get('401', []):
        hrv.append({'local_timestamp_fit_seconds': item.get(0), 'hrv_values_ms': item.get(2),
                    'baseline_min_ms': item.get(3), 'baseline_max_ms': item.get(4),
                    'array_order_and_dates': 'unverified; values may be rolling weekly averages rather than nightly averages'})
    result = {'source': str(args.file), 'interpretation': 'Experimental Gadgetbridge field mapping; validate against the watch.',
              'daily_sleep': daily, 'sleep_stage_summaries': stages, 'hrv_stats': hrv,
              'naps': messages.get('nap_event_mesgs', [])}
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
