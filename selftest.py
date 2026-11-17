"""Assert output shape, repeatability, and fallback behavior of main.py."""

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

INPUT_DIR = Path(os.environ.get(
    "MAKEFUN_TEST_INPUT_DIR",
    "/data/openmausbot/task-workspaces/cb6ed791-2564-4423-bd3d-46567e37b2a8/3ac7bee4-d5a9-4b08-87fd-4d4a5390d2b4/makefun/gta-kit/gta6-twitch-ccu-forecast-01-kit/input",
))
ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "main.py"


def check_output(path):
    raw = path.read_bytes()
    data = json.loads(raw)
    assert isinstance(data, dict) and list(data) == ["hours"]
    rows = data["hours"]
    assert isinstance(rows, list) and len(rows) == 23
    assert [row["hour"] for row in rows] == list(range(2, 25))
    for row in rows:
        values = row["q"]
        assert isinstance(values, list) and len(values) == 5
        assert all(isinstance(x, (int, float)) and math.isfinite(x) and 0 < x <= 1e9 for x in values)
        assert all(a <= b for a, b in zip(values, values[1:]))
    return raw, data


def run(input_dir, output_dir):
    env = os.environ.copy()
    env["MAKEFUN_INPUT_DIR"] = str(input_dir)
    env["MAKEFUN_OUTPUT_DIR"] = str(output_dir)
    subprocess.run([sys.executable, str(MAIN)], cwd=ROOT, env=env, check=True)


def main():
    if not INPUT_DIR.is_dir():
        print(f"SKIP: practice input directory not found: {INPUT_DIR}")
        return
    cases = sorted(INPUT_DIR.glob("*.in"), key=lambda path: path.name)
    assert len(cases) == 4, f"expected four practice cases, found {len(cases)}"
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        first, second = base / "first", base / "second"
        first.mkdir()
        second.mkdir()
        run(INPUT_DIR, first)
        run(INPUT_DIR, second)
        for case in cases:
            name = f"{case.stem}.out"
            one, _ = check_output(first / name)
            two, _ = check_output(second / name)
            assert one == two, f"non-deterministic output: {name}"
            print(f"PASS {name}: valid and byte-identical")

        for label, edit in (
            ("empty comparables", lambda data: data.update(comparables=[])),
            ("string hour-1 viewers", lambda data: next(r for r in data["known"] if r["hour"] == 1).update(viewers="not-a-number")),
        ):
            source = json.loads(cases[0].read_text(encoding="utf-8"))
            edit(source)
            input_dir = base / ("input-" + label.replace(" ", "-"))
            output_dir = base / ("output-" + label.replace(" ", "-"))
            input_dir.mkdir()
            input_dir.joinpath("broken.in").write_text(json.dumps(source), encoding="utf-8")
            run(input_dir, output_dir)
            _, output = check_output(output_dir / "broken.out")
            assert output == __import__("main").baseline(1 if label == "string hour-1 viewers" else source["known"][0]["viewers"])
            print(f"PASS fallback {label}: valid house-baseline output")

    print("All self-tests passed.")


if __name__ == "__main__":
    main()
