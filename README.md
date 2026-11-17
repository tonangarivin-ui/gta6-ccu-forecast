# gta6-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/tonangarivin-ui/gta6-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/tonangarivin-ui/gta6-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Entry for make.fun's *Forecast GTA VI's launch-day Twitch viewers hour by hour*: given hour 1's
print of the "Grand Theft Auto VI" Twitch category on 2026-11-19 UTC, write the 5/25/50/75/95%
quantiles of the category's viewer count for each hour 2 to 24, scored by mean pinball loss on
the log scale.

## Method

`main.py` (Python 3.13, standard library only, no network) forecasts each hour's log-offset from
hour 1. For every past launch in the case's `comparables`, it measures
`ln(views_h / views_1)` for each hour, then takes a weighted empirical quantile of those offsets
at each requested level. The weight is a Gaussian kernel on the launch-size feature
`ln(views_1)`, bandwidth 0.7, so comparables of similar size dominate; the 23x5 offset table is
then smoothed with a small `[0.36, 0.6, 1.0, 0.6, 0.36]` hour kernel. The forecast row is
`views_1 * exp(offset)`, rounded to two decimals, monotone within the row.

Backtested leave-one-out over the case's comparables, restricted to the eight launches nearest in
size: mean pinball loss ≈ 0.17 with 90% coverage ≈ 0.85, against ≈ 0.39 for the house baseline.
Malformed data, unusable comparables or a failed self-check fall back to that baseline, so a case
is never left without a valid 23-row answer.

## Run

```
mkdir -p out
MAKEFUN_INPUT_DIR=/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads `<id>.in` cases from the input directory, writes `<id>.out` for each. Deterministic: the
same input always produces byte-identical output, in well under a second per case.

Run `python3 selftest.py` to validate the four practice cases and both fallback paths; set
`MAKEFUN_TEST_INPUT_DIR` to override the practice input directory (Python 3.13, standard library only).

## License

MIT, see [LICENSE](LICENSE).

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
