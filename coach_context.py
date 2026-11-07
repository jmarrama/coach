#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["garmin-fit-sdk>=21"]
# ///
"""Build a compact local coaching brief; decode each FIT content version once."""
import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from statistics import mean
import tempfile
from zoneinfo import ZoneInfo

from garmin_fit_sdk import Decoder, Stream
from inspect_garmin_recovery import stamp

ROOT = Path(__file__).resolve().parent
STORE = ROOT / 'coaching'
TZ = ZoneInfo('America/Los_Angeles')
VERSION = 1


def atomic(path, value):
    fd, name = tempfile.mkstemp(prefix='.context-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(value)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def decode(path):
    messages, errors = Decoder(Stream.from_file(str(path))).read()
    if errors:
        raise ValueError(str(errors))
    sessions = []
    for i, s in enumerate(messages.get('session_mesgs', [])):
        start = s.get('start_time')
        if not isinstance(start, datetime):
            continue
        sessions.append(dict(id=f'{path.name}:{i}', start=start.isoformat(),
            day=start.astimezone(TZ).date().isoformat(), sport=s.get('sport'),
            sub_sport=s.get('sub_sport'), km=round(s.get('total_distance', 0)/1000, 2),
            minutes=round(s.get('total_timer_time', 0)/60, 1),
            avg_hr=s.get('avg_heart_rate'), max_hr=s.get('max_heart_rate'),
            aerobic_te=s.get('total_training_effect'), anaerobic_te=s.get('total_anaerobic_training_effect'),
            ascent_m=s.get('total_ascent')))
    sleep = []
    for s in messages.get('384', []):
        end, start = stamp(s.get(11)), stamp(s.get(9))
        if not end or not start:
            continue
        sleep.append(dict(start=start, end=end,
            day=datetime.fromisoformat(end).astimezone(TZ).date().isoformat(),
            interval_h=round((datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()/3600, 2),
            score=s.get(2), awake_min=s.get(24), sleep_min_hr=s.get(0)))
    hrv = [{k: str(v) if isinstance(v, datetime) else v for k, v in s.items()
            if k in ('timestamp', 'last_night_average', 'weekly_average', 'status')}
           for s in messages.get('hrv_status_summary_mesgs', [])]
    return dict(sessions=sessions, sleep=sleep, hrv=hrv)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=date.fromisoformat, default=datetime.now(TZ).date())
    args = parser.parse_args()
    STORE.mkdir(exist_ok=True)
    cache_dir = STORE / 'cache'
    archive = STORE / 'raw'
    cache_dir.mkdir(exist_ok=True)
    archive.mkdir(exist_ok=True)
    sessions, sleep, hrv, failures = {}, {}, {}, []
    decoded = 0
    paths = sorted(p for p in (ROOT / 'activities').rglob('*') if p.suffix.lower() == '.fit')
    # Cached historical recovery remains available after rolling backups drop it.
    historical = []
    for path in paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        saved = archive / f'{digest}.fit'
        if not saved.exists():
            saved.write_bytes(raw)
        cached = cache_dir / f'v{VERSION}-{digest}.json'
        try:
            if cached.exists():
                data = json.loads(cached.read_text())
            else:
                data = decode(path)
                atomic(cached, json.dumps(data, default=str))
                decoded += 1
            historical.append(cached)
            for s in data['sessions']:
                # Stable across renamed/copied files; retain multisport sessions.
                sessions[(s['start'], s['sport'], s['sub_sport'])] = s
            for s in data['sleep']:
                sleep[(s['start'], s['end'])] = s
            for s in data['hrv']:
                hrv[str(s.get('timestamp'))] = s
        except Exception as e:
            failures.append(f'{path.relative_to(ROOT)}: {e}')
    current_sleep = dict(sleep)
    # Rebuild historical caches from preserved snapshots when needed.
    for saved in archive.glob('*.fit'):
        cached = cache_dir / f'v{VERSION}-{saved.stem}.json'
        if not cached.exists():
            try:
                atomic(cached, json.dumps(decode(saved), default=str))
            except Exception as e:
                failures.append(f'archive {saved.name}: {e}')
    for cached in sorted(cache_dir.glob(f'v{VERSION}-*.json')):
        if cached in historical:
            continue
        for s in json.loads(cached.read_text()).get('sleep', []):
            sleep.setdefault((s['start'], s['end']), s)
    # Current snapshots win on revised intervals sharing a local wake date.
    nights = {s['day']: s for s in sorted(sleep.values(), key=lambda x: x['end'])}
    nights.update({s['day']: s for s in sorted(current_sleep.values(), key=lambda x: x['end'])})
    today = args.date
    runs = sorted((s for s in sessions.values() if s['sport'] == 'running' and s['day'] <= str(today)), key=lambda s: s['start'])
    recent = [s for s in sessions.values() if str(today-timedelta(days=13)) <= s['day'] <= str(today)]
    latest = max((s['day'] for s in sessions.values()), default='none')
    latest_sleep = max(nights, default='none')
    lines = [f'# Coaching brief | {today} | America/Los_Angeles',
             f'Built {datetime.now(TZ).isoformat(timespec="seconds")}; latest activity {latest}; latest sleep {latest_sleep}.',
             f'Coverage: {len(paths)} current FIT files, {len(sessions)} sessions, {len(nights)} sleep dates; {len(failures)} decode failures.',
             'Missing days are unknown, not confirmed rest. Refresh after USB sync. No validated readiness/recovery-time/current nightly HRV unless shown below.',
             '\n## Athlete', (STORE/'profile.md').read_text().strip(),
             '\n## Current plan', (STORE/'state.md').read_text().strip(),
             '\n## Running volume (rolling 7-day blocks; miles / minutes / runs)']
    for i in range(8):
        end = today-timedelta(days=7*i)
        start = end-timedelta(days=6)
        group = [s for s in runs if str(start) <= s['day'] <= str(end)]
        lines.append(f'{start}–{end}: {sum(s["km"] for s in group)/1.609344:.1f} / {sum(s["minutes"] for s in group):.0f} / {len(group)}')
    lines.append('\n## Last 14 days: all sessions (timer time; pace m:ss/mi)')
    for s in sorted(recent, key=lambda s: s['start']):
        seconds = round(s['minutes']*60*1.609344/s['km']) if s['km'] else None
        pace = f'{seconds//60}:{seconds%60:02d}/mi' if seconds is not None else '?'
        lines.append(f'{s["day"]} {s["sport"]}/{s["sub_sport"]}: {s["km"]/1.609344:.2f}mi {s["minutes"]}min pace={pace} HR={s["avg_hr"]}/{s["max_hr"]} TE={s["aerobic_te"]}/{s["anaerobic_te"]} ascent={s["ascent_m"]}m')
    lines.append('\n## Recent sleep (experimental mapping; interval includes awake time; minimum HR ≠ RHR)')
    for day, s in sorted(nights.items()):
        if str(today-timedelta(days=6)) <= day <= str(today):
            lines.append(f'{day}: score={s["score"]} interval={s["interval_h"]}h awake={s["awake_min"]}min minHR={s["sleep_min_hr"]}')
    scores = [s['score'] for day, s in nights.items() if str(today-timedelta(days=27)) <= day <= str(today) and isinstance(s['score'], (int,float))]
    lines.append(f'28-day mean sleep score: {mean(scores):.1f} (n={len(scores)})' if scores else 'No recent sleep scores.')
    lines.append('Official HRV summaries (if captured): '+json.dumps(list(hrv.values())[-7:], default=str))
    lines.append('\n## Recent coaching decisions (proposals ≠ completed workouts)')
    journal = STORE/'journal.jsonl'
    entries = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()] if journal.exists() else []
    lines.extend(json.dumps(e, separators=(',', ':')) for e in entries[-8:])
    if failures:
        lines.append('\nDecode failures: '+json.dumps(failures))
    brief = '\n'.join(lines)+'\n'
    atomic(STORE/'brief.md', brief)
    atomic(STORE/'sessions.json', json.dumps(sorted(sessions.values(), key=lambda s: s['start']), indent=2))
    atomic(STORE/'sleep.json', json.dumps(list(nights.values()), indent=2))
    print(brief)
    print(f'Cache: decoded {decoded}; reused {len(paths)-decoded-len(failures)}. Full history: coaching/sessions.json, sleep.json.')
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
