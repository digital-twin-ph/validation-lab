"""Check 46: Fieldwork's space-time scan, on Hagelloch, 1861, against an independent scan in numpy.

Fieldwork experiment 200 (Detect): Space-time scan runs the retrospective space-time permutation scan (Kulldorff and
others, 2005) on a line list with dates and places. The fixture is that scan run through Fieldwork's own code, on
Hagelloch's 188 cases by day of prodrome, 999 shuffles, seed 20261110.

**Independent.** Here the same model is written again from its definition in numpy. It scores EVERY run of days, where
Fieldwork tries only runs that start and end on a day with a case in the circle; so it also tests that shortcut. It
shuffles the dates with numpy's own generator, so its p-values cannot share Fieldwork's random stream. Nothing of
Fieldwork's code is read.

Criteria, fixed before running:

1. **The same scan**: the same number of circles, runs and windows.
2. **The same clusters**: for each cluster reported, the same places, days, observed and expected cases, and score
   (to 1e-9).
3. **P-values within Monte Carlo error**: each differs from Fieldwork's by no more than three standard errors of the
   difference of two independent estimates, plus the 1/(R+1) step of each.

What this cannot establish: that a cluster is an outbreak, or that the model suits measles in a village. Both sides
compute the same statistic; neither says what it means.

Design record: fieldwork/docs/experiments/200-operational-epidemiology.md
"""
from __future__ import annotations

import json
import math
import pathlib
import platform
import sys
import time
from datetime import date, datetime, timezone

import numpy as np

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "scan-hagelloch-001.json"
RESULT = HERE.parent / "results" / "check-46-space-time-scan.json"
EARTH_KM = 6371.0088
NUMPY_SEED = 46


def haversine(a, b):
    lon1, lat1, lon2, lat2 = map(np.radians, (a[0], a[1], b[:, 0], b[:, 1]))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.minimum(1, np.sqrt(h)))


def best_scores(circle_bins, share, n, longest, keep=False):
    """The best run of every circle: every start, every length up to the longest."""
    circles, bins = circle_bins.shape
    p = np.concatenate([np.zeros((circles, 1)), np.cumsum(circle_bins, axis=1)], axis=1)
    t = np.concatenate([[0.0], np.cumsum(circle_bins_total_cache["t"])])
    best = np.zeros(circles)
    where = np.zeros((circles, 4))  # a, b, c, e
    for length in range(1, longest + 1):
        c = p[:, length:] - p[:, :-length]
        e = share[:, None] * (t[length:] - t[:-length])[None, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            llr = np.where(c > e, c * np.log(c / e) + np.where(n - c > 0, (n - c) * np.log((n - c) / (n - e)), 0), 0)
        llr = np.nan_to_num(llr)
        a = llr.argmax(axis=1)
        top = llr[np.arange(circles), a]
        better = top > best + 1e-12
        if keep:
            rows = np.nonzero(better)[0]
            where[rows] = np.stack([a[rows], a[rows] + length - 1, c[rows, a[rows]], e[rows, a[rows]]], axis=1)
        best = np.where(better, top, best)
    return (best, where) if keep else best


circle_bins_total_cache: dict = {}


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    s = fixture["declaredParameters"]
    cases = [c for c in fixture["input"]["cases"] if c["date"] and c["lon"] is not None and c["lat"] is not None]
    days = [date.fromisoformat(c["date"][:10]).toordinal() for c in cases]
    first, last = min(days), max(days)
    bins = last - first + 1
    n = len(cases)
    keys = [f'{c["lon"]:.6f},{c["lat"]:.6f}' for c in cases]
    order = sorted(set(keys), key=keys.index)
    place_of = np.array([order.index(k) for k in keys])
    coords = np.array([[float(k.split(",")[0]), float(k.split(",")[1])] for k in order])
    places = len(order)
    case_bin = np.array(days) - first
    place_cases = np.bincount(place_of, minlength=places)

    # Circles: places in order of distance, ties together, up to the share of cases. Each set once.
    cap = n * s["maxCaseShare"]
    seen, members = set(), []
    for centre in range(places):
        d = haversine(coords[centre], coords)
        ranked = sorted(range(places), key=lambda p: (d[p], p))
        taken, cases_in, k = [], 0, 0
        while k < places:
            j, add = k, 0
            while j < places and abs(d[ranked[j]] - d[ranked[k]]) < 1e-9:
                add += place_cases[ranked[j]]
                j += 1
            if cases_in + add > cap + 1e-9:
                break
            taken += ranked[k:j]
            cases_in += add
            k = j
            key = frozenset(taken)
            if key not in seen:
                seen.add(key)
                members.append(key)
    membership = np.zeros((len(members), places))
    for i, m in enumerate(members):
        membership[i, list(m)] = 1
    share = membership @ place_cases / n
    longest = max(1, math.floor(bins * s["maxTimeShare"]))
    runs = sum(min(longest, bins - a) for a in range(bins))

    def place_bins(assign):
        grid = np.zeros((places, bins))
        np.add.at(grid, (place_of, assign), 1)
        return grid

    circle_bins_total_cache["t"] = np.bincount(case_bin, minlength=bins).astype(float)
    best, where = best_scores(membership @ place_bins(case_bin), share, n, longest, keep=True)

    # Clusters: by score, then observed, then earliest start; no place shared with one before.
    ranking = sorted(range(len(members)), key=lambda i: (-best[i], -where[i, 2], where[i, 0]))
    used, mine = set(), []
    for i in ranking:
        if len(mine) >= s["report"] or best[i] <= 0:
            break
        if members[i] & used:
            continue
        used |= members[i]
        mine.append(i)

    # Shuffles, with numpy's own generator: the dates moved across the fixed cases.
    rng = np.random.default_rng(NUMPY_SEED)
    replications = s["replications"]
    began = time.perf_counter()
    maxima = np.empty(replications)
    for r in range(replications):
        maxima[r] = best_scores(membership @ place_bins(rng.permutation(case_bin)), share, n, longest).max()
    seconds = time.perf_counter() - began

    theirs = fixture["output"]
    dated = lambda b: date.fromordinal(first + int(b)).isoformat()
    differs, pvalues = [], []
    for rank, i in enumerate(mine, start=1):
        got = theirs["clusters"][rank - 1] if rank <= len(theirs["clusters"]) else None
        a, b, c, e = where[i]
        p_mine = (1 + int((maxima + 1e-9 >= best[i]).sum())) / (1 + replications)
        mine_row = {"rank": rank, "places": sorted(f"{coords[p][0]:.6f},{coords[p][1]:.6f}" for p in members[i]),
                    "start": dated(a), "end": dated(b), "observed": int(c), "expected": float(e), "llr": float(best[i]),
                    "pValue": p_mine}
        problems = []
        if got is None:
            problems.append("not reported by Fieldwork")
        else:
            if sorted(f"{x[0]:.6f},{x[1]:.6f}" for x in got["places"]) != mine_row["places"]:
                problems.append("different places")
            for key in ("start", "end", "observed"):
                if got[key] != mine_row[key]:
                    problems.append(f"{key} {got[key]} != {mine_row[key]}")
            for key in ("expected", "llr"):
                if abs(got[key] - mine_row[key]) > 1e-9:
                    problems.append(f"{key} {got[key]} != {mine_row[key]}")
            p_bar = (got["pValue"] + p_mine) / 2
            allowed = 3 * math.sqrt(2 * p_bar * (1 - p_bar) / replications) + 2 / (replications + 1)
            pvalues.append({"rank": rank, "fieldwork": got["pValue"], "here": p_mine, "allowed": allowed,
                            "within": abs(got["pValue"] - p_mine) <= allowed})
            if abs(got["pValue"] - p_mine) > allowed:
                problems.append(f"p {got['pValue']} vs {p_mine}, allowed {allowed:.4f}")
        if problems:
            differs.append({"rank": rank, "problems": problems})
    if len(mine) != len(theirs["clusters"]):
        differs.append({"rank": None, "problems": [f"{len(theirs['clusters'])} clusters reported, {len(mine)} here"]})

    totals = {"cases": n, "places": places, "bins": bins, "circles": len(members), "runs": runs,
              "windows": len(members) * runs}
    same_scan = all(theirs["totals"][k] == v for k, v in totals.items())
    top = theirs["clusters"][0]
    return {
        "check": "46-space-time-scan",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": same_scan and not differs,
        "criteria": "The same circles, runs and windows; for every cluster the same places, days, observed and expected "
                    "cases and score to 1e-9; p-values within three standard errors of the difference plus the 1/(R+1) step",
        "totals": totals,
        "mostLikely": {"places": len(top["places"]), "start": top["start"], "end": top["end"],
                       "observed": top["observed"], "expected": round(top["expected"], 4), "pValue": top["pValue"]},
        "pValues": pvalues,
        "differs": differs,
        "shuffles": {"replications": replications, "generator": "numpy default_rng (PCG64)", "seed": NUMPY_SEED,
                     "seconds": round(seconds, 1)},
        "notEstablished": [
            "That a cluster is an outbreak: both sides compute the same statistic; neither says what it means.",
            "That the space-time permutation model suits measles in a village: it compares timing across places and "
            "cannot see where people live.",
            "That the p-values are the same to the digit: they come from different random numbers, so they agree only "
            "within Monte Carlo error.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "numpy": np.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
