"""Forecast launch-day Twitch viewers from kernel-weighted comparable launches.

Hourly log-offset quantiles are weighted by the launch-hour-1 level, then
smoothed over time; malformed case data falls back to the house forecast.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
ZS = (-1.645, -0.674, 0.0, 0.674, 1.645)
SMOOTH = (0.36, 0.6, 1.0, 0.6, 0.36)


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def weighted_quantile(items, tau):
    items.sort(key=lambda item: item[0])
    threshold = tau * sum(weight for _, weight in items)
    cumulative = 0.0
    for value, weight in items:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return items[-1][0]


def model(data, p):
    case_lv1 = math.log(max(float(p), 1.0))
    usable = []
    for comparable in data["comparables"]:
        start = parse_time(comparable["day_start"])
        by_time = {parse_time(point["from"]): point["viewers"] for point in comparable["hourly"]}
        values = [by_time.get(start + timedelta(hours=i)) for i in range(24)]
        if any(value is None or float(value) == 0 for value in values):
            continue
        values = [float(value) for value in values]
        lv1 = math.log(max(values[0], 1.0))
        weight = math.exp(-0.5 * ((lv1 - case_lv1) / 0.7) ** 2)
        usable.append((values, weight))
    if not usable:
        raise ValueError("no usable comparables")

    offsets = []
    for index in range(1, 24):
        levels = []
        for tau in LEVELS:
            samples = [(math.log(values[index] / values[0]), weight) for values, weight in usable]
            levels.append(weighted_quantile(samples, tau))
        offsets.append(levels)

    smoothed = []
    for hour_index in range(23):
        row = []
        for level_index in range(5):
            weighted = [(offsets[j][level_index], SMOOTH[j - hour_index + 2])
                        for j in range(max(0, hour_index - 2), min(23, hour_index + 3))]
            weight_sum = sum(weight for _, weight in weighted)
            row.append(sum(value * weight for value, weight in weighted) / weight_sum)
        smoothed.append(row)

    rows = []
    for hour, offset_row in enumerate(smoothed, 2):
        q = [min(1e9, max(0.01, js_round(float(p) * math.exp(offset)))) for offset in offset_row]
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
