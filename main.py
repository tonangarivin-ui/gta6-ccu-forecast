"""Forecast launch-day Twitch viewers from kernel-weighted comparable launches.

Each hour's log-offset uses a level-adjusted pool fit and a MAD spread,
priced as a normal; malformed case data falls back to the house forecast.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
ZS = (-1.645, -0.674, 0.0, 0.674, 1.645)
EARLY_TERMS = ("early access", "early-access", "premium")  # These launches started days earlier; hour 1 is a second day in.
GLOBAL_TERMS = ("single global", "simultaneous", "global unlock", "single time", "10:00 utc", "10 am")  # One worldwide unlock puts hour 1 before the wave.
ROLLING_TERMS = ("midnight", "rolling")  # A midnight-local launch still rises slowly after hour 1.
BANDWIDTH = 0.5  # The pool is big and heterogeneous; only near-neighbours should shape the curve.
SIGMA_SCALE = 0.45
LEVEL_SLOPE = 0.9
SIGMA_FLOOR = 0.6  # The pool's disagreement understates real uncertainty on a single launch.
POOL_MIX = 0.2  # Shrink each hour 20% toward the whole pool's unweighted median shape.


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nth_sunday(year, month, n):
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def us_midnight_hour(day):
    """Hour index (1-24) of the UTC hour in which US Eastern midnight falls on `day`."""
    start = _nth_sunday(day.year, 3, 2)
    end = _nth_sunday(day.year, 11, 1)
    offset = -4 if start.date() <= day < end.date() else -5
    return ((-offset) % 24) + 1


def js_round(value):
    rounded = math.floor(value * 100 + 0.5) / 100
    return int(rounded) if rounded.is_integer() else rounded


def baseline(p):
    p = min(max(float(p), 0.01), 1e9)
    rows = []
    for hour in range(2, 25):
        spread = 0.15 * math.sqrt(hour - 1)
        q = [min(1e9, max(0.01, js_round(p * math.exp(z * spread)))) for z in ZS]
        for i in range(1, 5):
            q[i] = max(q[i], q[i - 1])
        rows.append({"hour": hour, "q": q})
    return {"hours": rows}


def valid_output(output):
    try:
        rows = output["hours"]
        return (
            isinstance(rows, list)
            and len(rows) == 23
            and [row["hour"] for row in rows] == list(range(2, 25))
            and all(
                isinstance(row["q"], list)
                and len(row["q"]) == 5
                and all(isinstance(value, (int, float)) and math.isfinite(value) and 0 < value <= 1e9
                        for value in row["q"])
                and all(a <= b for a, b in zip(row["q"], row["q"][1:]))
                for row in rows
            )
        )
    except (KeyError, TypeError):
        return False


def valid_case(data):
    forecast = data.get("forecast")
    if not isinstance(forecast, list) or len(forecast) != 23:
        return False
    try:
        if [row["hour"] for row in forecast] != list(range(2, 25)):
            return False
    except (TypeError, KeyError):
        return False
    return "levels" not in data or data["levels"] == list(LEVELS)


def weighted_median(items):
    items.sort(key=lambda item: item[0])
    threshold = sum(weight for _, weight in items) / 2
    cumulative = 0.0
    for value, weight in items:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return items[-1][0]


def build_comparables(data, case_lv1):
    unfiltered = []
    filtered = []
    try:
        case_day = parse_time(data["day_start"]).date()
        case_shift_base = us_midnight_hour(case_day)
    except (TypeError, ValueError, KeyError):
        case_shift_base = 0
    for comparable in data["comparables"]:
        start = parse_time(comparable["day_start"])
        by_time = {parse_time(point["from"]): point["viewers"] for point in comparable["hourly"]}
        values = [by_time.get(start + timedelta(hours=i)) for i in range(24)]
        if any(value is None or float(value) == 0 for value in values):
            continue
        values = [float(value) for value in values]
        lv1 = math.log(max(values[0], 1.0))
        weight = math.exp(-0.5 * ((lv1 - case_lv1) / BANDWIDTH) ** 2)
        try:
            comparable_day = parse_time(comparable["day_start"]).date()
            shift = us_midnight_hour(comparable_day) - case_shift_base
        except (TypeError, ValueError, KeyError):
            shift = 0
        item = (values, weight, shift)
        unfiltered.append(item)
        unlock = str(comparable.get("unlock", "")).lower()
        if (not any(term in unlock for term in EARLY_TERMS)
                and (any(term in unlock for term in ROLLING_TERMS)
                     or not any(term in unlock for term in GLOBAL_TERMS))):
            filtered.append(item)
    return filtered or unfiltered, len(filtered)


def model(data, p):
    case_lv1 = math.log(max(float(p), 1.0))
    usable, _ = build_comparables(data, case_lv1)
    if not usable:
        raise ValueError("no usable comparables")

    levels = [math.log10(values[0]) for values, _, _ in usable]
    lo, hi = min(levels), max(levels)
    case_level = max(lo, min(hi, math.log10(max(float(p), 1.0))))  # Clamp: a launch bigger than every comparable keeps the biggest one's shape.
    centers = []
    sigmas = []
    for index in range(1, 24):
        aligned = [(math.log(values[max(0, min(23, index + shift))] / values[0]), weight, level)
                   for (values, weight, shift), level in zip(usable, levels)]
        samples = [(offset, weight) for offset, weight, _ in aligned]
        center = weighted_median(list(samples))
        spread = 1.4826 * weighted_median(
            [(abs(value - center), weight) for value, weight in samples]
        )
        pairs = [(level, offset) for offset, _, level in aligned]
        mean_x = sum(level for level, _ in pairs) / len(pairs)
        mean_y = sum(offset for _, offset in pairs) / len(pairs)
        denominator = sum((level - mean_x) ** 2 for level, _ in pairs)
        slope = (LEVEL_SLOPE * sum((level - mean_x) * (offset - mean_y)
                                   for level, offset in pairs) / denominator
                 if denominator else 0.0)
        center = mean_y + slope * (case_level - mean_x)
        pool_center = weighted_median([(offset, 1.0) for offset, _, _ in aligned])
        center = (1 - POOL_MIX) * center + POOL_MIX * pool_center
        centers.append(center)
        sigmas.append(max(spread, SIGMA_FLOOR))

    rows = []
    for hour_index, hour in enumerate(range(2, 25)):
        q = [min(1e9, max(0.01, js_round(float(p) * math.exp(
            centers[hour_index] + z * SIGMA_SCALE * sigmas[hour_index]
        )))) for z in ZS]
        for i in range(1, 5):
            q[i] = max(q[i], q[i - 1])
        rows.append({"hour": hour, "q": q})
    return {"hours": rows}


def main():
    input_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    output_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    for input_path in sorted(input_dir.glob("*.in"), key=lambda path: path.name):
        try:
            data = json.loads(input_path.read_text(encoding="utf-8"))
            known = data.get("known")
            hour_one = next((row for row in known if isinstance(row, dict) and row.get("hour") == 1), None) if isinstance(known, list) else None
            try:
                raw_p = hour_one["viewers"]
                if isinstance(raw_p, bool):
                    raise ValueError("boolean viewer count")
                p = float(raw_p)
                if not math.isfinite(p):
                    raise ValueError("non-finite viewer count")
                p = max(p, 0.01)
            except (TypeError, ValueError, KeyError):
                p = 1.0
                output = baseline(p)
            else:
                if not valid_case(data):
                    continue
                try:
                    output = model(data, p)
                except Exception:
                    output = baseline(p)
            if not valid_output(output):
                output = baseline(p)
        except Exception:
            output = baseline(1.0)
        (output_dir / f"{input_path.stem}.out").write_text(
            json.dumps(output, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
