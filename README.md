# Roblox Up-and-Coming Top 10 Forecast — make.fun bounty entry

Forecasts Roblox's Up-and-Coming chart top 10 for the 72 hours after entries
close, as place-by-place probabilities plus a top-10 guess. Python 3.13,
standard library only, no network, deterministic.

## Model: empirical rank-transition kernel

- From every pair of snapshots in `/input/history.ndjson`, estimate
  P(rank at t+dt | rank at t) per lag bucket (0–6h, 6–14h, 14–26h, 26–44h,
  44–68h, 68–96h, 96–140h), smoothed over neighbouring source and target
  ranks, with an explicit "off chart" state.
- For each game on the last chart, average that distribution over the 72
  scored hours (first hours blended toward the current rank: the chart
  barely moves at first), and scale by an age-survival factor (games near
  or past the chart's 28-day window drop out faster; measured stay rates
  within 72h: age<=20d 93%, 21–27d 81%, 28d+ 54%; factor relative to the
  kernel's age-mixed average, so no double counting).
- Per place, name every game with P >= 0.0015 (cap 100 rows/place); the mass
  left unnamed covers new entrants and deep-chart games. top10 = the 10
  games with the lowest expected rank over the window.

## What the data said (and what was rejected)

- The chart churns hard: a top-10 game has only ~48% chance of still being
  top 10 after 48–84h; #1 changes ~13 times in 12 days.
- Player-count growth does NOT predict rank moves (corr -0.01) — the sort
  is computed, not a live count. Rank history is the signal.
- Rank-velocity extrapolation was tested and REJECTED: it helped the fresh
  window (+0.5) but badly hurt the practice window (-2.7). Rank moves are
  mostly noise; the unconditional kernel is the honest forecast.
- An age-survival factor was tested and REJECTED too: the 28-day chart
  window is soft (28d+ games still stay on the chart 54% of the time) and
  the kernel's "off chart" state already prices dropout (net -0.37).

## Backtest (measured, exact scorer per RULES.txt)

| window | history ends | answers | model | house baseline | delta |
|---|---|---|---|---|---|
| practice | 2026-11-07 20:53Z | 10 archive reads, 8–10 Nov | -34.059 | -43.512 | +9.45 |
| fresh | 2026-11-10 17:51Z | 3 archive reads, 10–11 Nov | -32.334 | -42.229 | +9.89 |

Scorer verified to reproduce the house baseline's published practice score
exactly (-43.512039). Runs are byte-identical on repeat; 100-snapshot input
runs in ~7s (limit 300s); forecast.json ~47KB (limit 1MB).

## Run

    python3 main.py            # reads $MAKEFUN_INPUT_DIR (else /input),
                               # writes $MAKEFUN_OUTPUT_DIR (else /output)
