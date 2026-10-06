"""Health check: are the scheduled jobs actually producing data?

Missing a day of collection is unrecoverable, so silence must not mean "fine". Each job writes
state/last_run_<job>.json when it finishes; this check fails when one is older than its schedule
allows. Prints a report and returns 1 on any FAIL, so a caller can alert on the exit code.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta

from .storage import DATA_DIR, read_json, utcnow

# Longest gap between scheduled runs (see scripts/install_launchd.sh) plus slack for run time.
MAX_AGE = {
    "leaderboard": timedelta(hours=26),  # daily
    "wallets": timedelta(hours=10),      # longest gap 18:30 -> 02:30 = 8h
    "normalize": timedelta(hours=18),    # longest gap 04:15 -> 19:45 = 15.5h
}
MAX_WALLET_FAILURE_RATE = 0.10
MIN_FREE_GB = 20


def check() -> list[tuple[str, str]]:
    """Returns (level, message) pairs; level is OK, WARN or FAIL."""
    now = utcnow()
    results = []

    for job, max_age in MAX_AGE.items():
        last = read_json(DATA_DIR / "state" / f"last_run_{job}.json", None)
        if last is None:
            results.append(("FAIL", f"{job}: has never finished"))
            continue
        age = now - datetime.fromisoformat(last["finished_at"])
        level = "OK" if age <= max_age else "FAIL"
        results.append((level, f"{job}: last finished {age.total_seconds() / 3600:.1f}h ago"))

    wallets = read_json(DATA_DIR / "state" / "last_run_wallets.json", None)
    if wallets:
        rate = wallets["failures"] / max(wallets["wallets"], 1)
        level = "OK" if rate <= MAX_WALLET_FAILURE_RATE else "FAIL"
        results.append((level, f"wallets: {wallets['failures']}/{wallets['wallets']} failed in last run"))
        if wallets["gap_suspected"]:
            results.append(("WARN", f"wallets: possible fill gaps for {len(wallets['gap_suspected'])} wallets "
                                    "(they trade faster than we poll)"))

    free_gb = shutil.disk_usage(DATA_DIR).free / 1e9
    results.append(("OK" if free_gb >= MIN_FREE_GB else "FAIL", f"disk: {free_gb:.0f} GB free"))
    return results


def main() -> int:
    results = check()
    for level, message in results:
        print(f"{level:4} {message}")
    return 1 if any(level == "FAIL" for level, _ in results) else 0
