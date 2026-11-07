# Garmin watch data map

Snapshot: Fenix 8, inspected November 5, 2026. The USB MTP sync copied 446 FIT files into `activities/00020001/GARMIN/`. Counts and contents are a point-in-time snapshot; later watch syncs may change them. Garmin FIT files can contain personal health data, location and device identifiers.

## Recovery discovery: sleep and HRV in the backup

`FbtBackup/lha_bkup.fit` contains substantial recovery history even though the watch's `Sleep` and `HRVStatus` folders were empty over MTP. The standard Garmin FIT SDK does not name all of the relevant message types. The message and field names below come from the [Gadgetbridge reverse-engineered FIT profile](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/branch/master/FitCodeGenerator/src/main/resources/fit_profile.json), and should be checked against the watch or Garmin Connect before being relied upon.

- **Message 384, `DAILY_SLEEP`: 100 records**, with sleep start/end timestamps, time-zone offsets, sleep score, minimum heart rate, awake minutes and quality score in populated fields. The observed sleep end timestamps span July 29 through November 5, 2026. These are per-night summaries, not a continuous overnight heart-rate or sleep-stage timeline. Some other fields in these messages are still unknown.
- **Message 411, `SLEEP_SUMMARY`: 7 records**, with start/end timestamps, sleep score and aggregate minutes of deep, light, REM, awake and unmeasurable sleep. All seven records' scores and timestamps match their corresponding daily-sleep entries. These are stage-duration totals, not timestamped transitions between sleep stages.
  For example, the most recent summary has a sleep score of 88 and reports 71 minutes deep, 360 minutes light, 112 minutes REM and 17 minutes awake. The owner confirmed that the scores and stage durations for November 3, 4 and 5 match Garmin Connect. Other field names and nights still need independent validation.
- **Message 401, `HRV_STATS`: 1 record** containing arrays of 28 HRV values and 28 each of lower and upper baseline values, in milliseconds according to Gadgetbridge. The owner confirmed nightly averages of 49 ms (Nov 5), 40 ms (Nov 4) and 40 ms (Nov 3). The final three array values are 40, 40, 41, so they do **not** match the nightly series. Training-readiness records for those dates identify weekly HRV averages of 41, 40 and 40 ms respectively, consistent with the end of the array being ordered oldest to newest and representing weekly averages. This is a strong hypothesis, not a verified date mapping. Do not treat these as nightly averages or assign dates without more validation.
- **Message 412, `nap_event`: 8 slots**, of which two have populated start/end timestamps (June 6 and October 3, 2026). The Garmin SDK recognizes these directly.
- **Message 369, `TRAINING_READINESS`:** present in multiple `Debug/MetricsBackup` files. The community profile identifies fields including sleep score, weekly HRV average and recovery time. These are further candidates; we have not yet validated their individual values or history.
- **Message 140, `PHYSIOLOGICAL_METRICS`:** the community profile identifies the 150 records in `FbtPtdBackup/ptd_bkup.fit` as activity-related physiological metrics, potentially including training effects, VO₂ max, recovery and lactate-threshold fields. Availability varies by record.

Run the experimental extractor:

```sh
uv run --script inspect_garmin_recovery.py > recovery.json
```

It outputs the daily sleep summaries, seven stage summaries, HRV arrays without assigning dates or asserting whether values are nightly or weekly, and nap records. The `index` fields are positions in this snapshot, not established permanent IDs. It reads the already-synced backup, requires `garmin-fit-sdk`, and does not contact or alter the watch. The output contains sensitive health information. Scores, field interpretations, units and array associations should be validated against known dates shown on the watch. Raw beat-to-beat intervals, overnight heart-rate curves and individual sleep-stage transitions have not yet been identified in this backup.

## Synced directories

| Directory | FIT files | Contents observed |
| --- | ---: | --- |
| Garmin root | 1 | `device.fit`: capabilities, supported file/message types, software and device information. |
| `Activity` | 290 | Recorded activity FITs. Sampled runs include GPS, heart rate, pace, elevation, cadence, power, running dynamics, training effect and training load. |
| `Sports` | 113 | Sport profile configurations, including activity-specific zones and targets; not 113 completed activities. |
| `Debug/MetricsBackup` | 24 | Small metric backups. Recognizable VO₂ max messages, and community-identified training-readiness records; many fields remain undocumented. |
| `FbtBackup` | 1 | `lha_bkup.fit`: 100 daily-sleep records, seven sleep-stage summaries, HRV arrays, naps, and other unidentified records. |
| `FbtPtdBackup` | 1 | `ptd_bkup.fit`: physiological-metrics history according to the community FIT profile. |
| `Monitor` | 2 | Brief all-day monitoring snapshots: walking/running totals, resting heart rate, sensor state and one stress reading. These do not provide a full overnight history. |
| `Coach` | 1 | `schedule.fit`: 12 structured workouts and 28 steps with duration and heart-rate or speed targets where available. |
| `Settings` | 1 | User/device configuration, including heart-rate and power zones, thresholds and configured sleep/wake times. The configured sleep times are not observed sleep. |
| `Totals` | 1 | Four aggregate records with sport, number of sessions, distance, timer time and calories. |
| `Goals` | 1 | One goal record with type, target and dates. |
| `Records` | 1 | 33 data messages with unrecognized types. Personal-record contents have not been confirmed. |
| `MltSport` | 2 | Triathlon and swimrun configuration files, mostly unrecognized message types. |
| `Clubs` | 1 | Clubs file with unrecognized messages; a golf connection is plausible but unconfirmed. |
| `Device` | 1 | Product, software and timestamp/device information. |
| `Calendar` | 1 | File metadata only in the decoded snapshot. |
| `Gear` | 1 | File metadata only in the decoded snapshot. |
| `Location` | 1 | File metadata only in the decoded snapshot. |
| `Schedule` | 1 | File metadata only in the decoded snapshot; separate from the populated `Coach` schedule. |
| `Seg_List` | 1 | File metadata only in the decoded snapshot. |

## Building a recovery history

- The 100 daily-sleep records include **minimum heart rate during sleep**, which is not established to be Garmin’s daily resting heart rate (RHR). Explicitly labeled RHR values appeared in the two short `Monitor` snapshots; a complete historical daily RHR series has not been found. Treat sleep minimum HR and RHR as separate metrics.
- The owner verified the November 3–5 sleep scores and stage durations against Garmin Connect. The 28 HRV values likely represent rolling weekly averages, not nightly averages; individual nightly values remain unavailable and the full date ordering is unverified.
- Rolling averages cannot uniquely recover nightly values without initial nightly values. For a seven-day average, `night[t] = 7 * (average[t] - average[t-1]) + night[t-7]`. If each average is rounded to the nearest 1 ms, rounding alone can introduce up to about 7 ms of error in the inferred nightly change, before errors in the earlier nightly value. Do not present reconstructed nights as measurements.
- RHR and HRV can provide complementary signals, but neither alone establishes recovery. Compare each person’s metrics with their own history alongside recent training, sleep and subjective fatigue; see the [Australian Institute of Sport guidelines](https://www.ais.gov.au/__data/assets/pdf_file/0013/1130260/HRV-BPG_FINAL.pdf).

### Preserve rolling snapshots

The sync now archives old and new content versions under `coaching/raw/<sha256>.fit` before replacing changed files. `coach_context.py` also archives current files, caches decoded summaries, and merges sleep history by local wake date (current snapshots win). Earlier overwritten versions cannot be recovered. Distinct sleeps on one wake date require raw inspection. See `coaching/README.md`.

Each decoded sleep record has absolute start and end timestamps. In the current snapshot, index 0 is most recent and larger indexes go backward; treat indexes as potentially shifting positions, not stable identifiers. We have not found a permanent sleep-session ID. A practical importer can match by device and sleep interval or local wake date, but must allow for revised start/end times and avoid silently merging distinct sessions. Time-zone offsets are present and can change across daylight saving time. No matching strategy has been validated against successive watch snapshots yet.

## Other watch files, not synced

The MTP listing exposed around 750 files of all types, including maps and other device assets. `GARMIN/Sleep`, `GARMIN/HRVStatus`, `GARMIN/SUMMARY`, and `GARMIN/SQL` had no files at the time of inspection. This describes the MTP view, not necessarily all of the watch's internal storage.

`GARMIN/PointCache` had 194 `.gpc` files. Of these, 193 shared exact basenames with activity FITs; the remaining file was `Temporary.gpc`. They appear to be activity point caches and are not copied by the FIT-only sync. The watch also exposes opaque `.bin`, `.dat`, and other files; their contents have not been fully decoded.

## Sync and limitations

```sh
uv run --script sync_garmin.py
```

The sync requires the Homebrew `libmtp` library and the watch connected in MTP mode. It preserves paths under the storage ID and saves `.garmin-sync.json` alongside the script. For previously copied files, it checks source size and modification time plus the destination's SHA-256; a source change that preserves both size and modification time may be missed. Initial sync copied 446 FIT files; a second run skipped all 446 unchanged.

The sync only sees files exposed over MTP. A separate Garmin Bluetooth sync protocol may expose other health files, but has not been tested successfully with this watch. For historical data already transferred off the watch, a Garmin Connect account export is another possible source.

## Overnight HRV sample investigation

A FIT-record-header scan of all 446 synced files found no message 371 (`hrv_value`, timestamped HRV values), message 370 (`hrv_status_summary`, which includes last-night average), or message 521 (community-identified `SLEEP_INSIGHT`). It also found no sleep-level message 275 or beat-interval message 290. This does not rule out unidentified proprietary representations, but no candidate sample series has been established. A fresh MTP listing again showed no files in `Sleep` or `HRVStatus`.

Garmin users report that the Connect app clears wellness FIT files after syncing ([Garmin forum discussion](https://forums.garmin.com/sports-fitness/healthandwellness/f/index-sleep-monitor/423093/manual-downloading-via-usb-is-pratically-impossible)); this is a plausible explanation, not proof of this device's behavior. To test: keep the watch from syncing over Bluetooth or Wi-Fi overnight, use the existing USB script to copy FIT files before the next Garmin sync, then inspect `activities/00020001/GARMIN/HRVStatus/` and `Sleep/`. Do not delete files from the watch. Once captured locally, normal syncing can resume.

`uv run --script analyze_overnight_hrv.py PATH` searches a FIT file or directory for timestamped HRV samples and reports their simple arithmetic mean. For a single file, add `--reported 49` (or that night's Garmin-displayed value) to compare. If the file has an HRV status summary, it also compares the FIT's nightly average. The script compares all samples in a file; verify they belong to the same sleep period and match the summary before interpreting a result. Multiple periods require separating/filtering them first. No real sample set has been available to validate this calculation yet.
