"""Check 46: Fieldwork's space-time scan, on Hagelloch, 1861, against an independent scan in numpy.

Fieldwork experiment 200 (Detect): Space-time scan runs the space-time permutation scan (Kulldorff and others, 2005,
PLoS Medicine 2(3):e59) on a line list with dates and places, once over the whole period (retrospective) or day by day
as the outbreak unfolded (prospective). The fixture is both, run through Fieldwork's own code, on Hagelloch's 188
cases by day of prodrome, 999 shuffles, seed 20261110.

**Independent.** Here the same model is written again from its definition in numpy. It scores EVERY run of days, where
Fieldwork tries only runs starting (and, looking back, ending) on a day with a case in the circle, so it also tests
that shortcut. It shuffles the dates with numpy's own generator, so its p-values cannot share Fieldwork's random
stream. Nothing of Fieldwork's code is read.

Criteria, fixed before running:

1. **The same scan**: the same number of circles, runs and windows.
2. **The same clusters**: for each cluster reported, the same places, days, observed and expected cases, and score
   (to 1e-9).
3. **P-values within Monte Carlo error**: each differs from Fieldwork's by no more than three standard errors of the
   difference of two independent estimates, plus the 1/(R+1) step of each.
4. **The same replay**: every day scanned or skipped alike, and each day's most likely cluster the same places, start,
   observed and expected cases and score (to 1e-9); its p-value within Monte Carlo error on every day Fieldwork's is
   at or under 0.1, the days that decide when a scan first flags.

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
REPLAY_P_CHECKED = 0.1


def haversine(a, b):
    lon1, lat1, lon2, lat2 = map(np.radians, (a[0], a[1], b[:, 0], b[:, 1]))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.minimum(1, np.sqrt(h)))


class Scan:
    """One scan's circles and cases, over days first..last."""

    def __init__(self, cases, first, last, case_share, time_share, tie_km=1e-9):
        self.bins = last - first + 1
        self.n = len(cases)
        keys = [f'{c["lon"]:.6f},{c["lat"]:.6f}' for c in cases]
        order = sorted(set(keys), key=keys.index)
        self.place_of = np.array([order.index(k) for k in keys])
        # A place is identified by its coordinates to 6 decimals; its distances are measured from the coordinates recorded
        # for its first case, as the fixture declares.
        first_of = {}
        for c, k in zip(cases, keys):
            first_of.setdefault(k, (float(c["lon"]), float(c["lat"])))
        self.coords = np.array([first_of[k] for k in order])
        self.places = len(order)
        self.case_bin = np.array([date.fromisoformat(c["date"][:10]).toordinal() - first for c in cases])
        place_cases = np.bincount(self.place_of, minlength=self.places)
        cap = self.n * case_share
        seen, self.members = set(), []
        for centre in range(self.places):
            d = haversine(self.coords[centre], self.coords)
            ranked = sorted(range(self.places), key=lambda p: (d[p], p))
            taken, held, k = [], 0, 0
            while k < self.places:
                j, add = k, 0
                while j < self.places and abs(d[ranked[j]] - d[ranked[k]]) <= tie_km:
                    add += place_cases[ranked[j]]
                    j += 1
                if held + add > cap + 1e-9:
                    break
                taken += ranked[k:j]
                held += add
                k = j
                key = frozenset(taken)
                if key not in seen:
                    seen.add(key)
                    self.members.append(key)
        self.membership = np.zeros((len(self.members), self.places))
        for i, m in enumerate(self.members):
            self.membership[i, list(m)] = 1
        self.share = self.membership @ place_cases / self.n
        self.longest = max(1, math.floor(self.bins * time_share))
        self.runs = sum(min(self.longest, self.bins - a) for a in range(self.bins))

    def best(self, assign, prospective=False, keep=False):
        """Every circle's best run; prospective, only runs ending on the last day."""
        grid = np.zeros((self.places, self.bins))
        np.add.at(grid, (self.place_of, assign), 1)
        circle_bins = self.membership @ grid
        circles = circle_bins.shape[0]
        p = np.concatenate([np.zeros((circles, 1)), np.cumsum(circle_bins, axis=1)], axis=1)
        t = np.concatenate([[0.0], np.cumsum(np.bincount(assign, minlength=self.bins))])
        n = self.n
        best = np.zeros(circles)
        where = np.zeros((circles, 4))
        for length in range(1, self.longest + 1):
            if prospective:
                a0 = self.bins - length
                if a0 < 0:
                    break
                c = (p[:, self.bins] - p[:, a0])[:, None]
                e = (self.share * (t[self.bins] - t[a0]))[:, None]
                starts = np.array([a0])
            else:
                c = p[:, length:] - p[:, :-length]
                e = self.share[:, None] * (t[length:] - t[:-length])[None, :]
                starts = np.arange(self.bins - length + 1)
            with np.errstate(divide="ignore", invalid="ignore"):
                llr = np.where(c > e, c * np.log(c / e) + np.where(n - c > 0, (n - c) * np.log((n - c) / (n - e)), 0), 0)
            llr = np.nan_to_num(llr)
            a = llr.argmax(axis=1)
            top = llr[np.arange(circles), a]
            # Ties: the earlier start, the shorter run, as Fieldwork keeps the first strictly higher.
            better = top > best + 1e-12
            if keep:
                rows = np.nonzero(better)[0]
                where[rows] = np.stack([starts[a[rows]], starts[a[rows]] + length - 1,
                                        c[rows, a[rows]], e[rows, a[rows]]], axis=1)
            best = np.where(better, top, best)
        return (best, where) if keep else best

    def maxima(self, replications, rng, prospective=False):
        return np.array([self.best(rng.permutation(self.case_bin), prospective).max() for _ in range(replications)])


def within(theirs, mine, replications):
    p_bar = (theirs + mine) / 2
    allowed = 3 * math.sqrt(2 * p_bar * (1 - p_bar) / replications) + 2 / (replications + 1)
    return abs(theirs - mine) <= allowed, allowed


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    s = fixture["declaredParameters"]
    replications = s["replications"]
    cases = [c for c in fixture["input"]["cases"] if c["date"] and c["lon"] is not None and c["lat"] is not None]
    ordinals = [date.fromisoformat(c["date"][:10]).toordinal() for c in cases]
    first, last = min(ordinals), max(ordinals)
    dated = lambda b: date.fromordinal(first + int(b)).isoformat()
    rng = np.random.default_rng(NUMPY_SEED)
    theirs = fixture["output"]
    differs = []

    # 1-3: the retrospective scan.
    tie = s.get("tieKm", 1e-9)
    scan = Scan(cases, first, last, s["maxCaseShare"], s["maxTimeShare"], tie)
    best, where = scan.best(scan.case_bin, keep=True)
    ranking = sorted(range(len(scan.members)), key=lambda i: (-best[i], -where[i, 2], where[i, 0]))
    used, mine = set(), []
    for i in ranking:
        if len(mine) >= s["report"] or best[i] <= 0:
            break
        if scan.members[i] & used:
            continue
        used |= scan.members[i]
        mine.append(i)
    began = time.perf_counter()
    maxima = scan.maxima(replications, rng)
    seconds = time.perf_counter() - began
    pvalues = []
    key = lambda xs: sorted(f"{x[0]:.6f},{x[1]:.6f}" for x in xs)  # compared by identity, to 6 decimals
    for rank, i in enumerate(mine, start=1):
        got = theirs["clusters"][rank - 1] if rank <= len(theirs["clusters"]) else None
        a, b, c, e = where[i]
        p_mine = (1 + int((maxima + 1e-9 >= best[i]).sum())) / (1 + replications)
        problems = []
        if got is None:
            problems.append("not reported by Fieldwork")
        else:
            if key(got["places"]) != key(scan.coords[list(scan.members[i])]):
                problems.append("different places")
            for name, value in (("start", dated(a)), ("end", dated(b)), ("observed", int(c))):
                if got[name] != value:
                    problems.append(f"{name} {got[name]} != {value}")
            for name, value in (("expected", float(e)), ("llr", float(best[i]))):
                if abs(got[name] - value) > 1e-9:
                    problems.append(f"{name} {got[name]} != {value}")
            ok, allowed = within(got["pValue"], p_mine, replications)
            pvalues.append({"rank": rank, "fieldwork": got["pValue"], "here": p_mine, "allowed": round(allowed, 4), "within": ok})
            if not ok:
                problems.append(f"p {got['pValue']} vs {p_mine}")
        if problems:
            differs.append({"rank": rank, "problems": problems})
    if len(mine) != len(theirs["clusters"]):
        differs.append({"rank": None, "problems": [f"{len(theirs['clusters'])} clusters reported, {len(mine)} here"]})
    totals = {"cases": scan.n, "places": scan.places, "bins": scan.bins, "circles": len(scan.members), "runs": scan.runs,
              "windows": len(scan.members) * scan.runs}
    same_scan = all(theirs["totals"][k] == v for k, v in totals.items())

    # 4: the replay, one prospective scan a day.
    replay_differs, replay_p = [], []
    began = time.perf_counter()
    for day in theirs["replay"]["days"]:
        until = date.fromisoformat(day["day"]).toordinal()
        known = [c for c, o in zip(cases, ordinals) if o <= until]
        if len(known) < 4 or len({(c["lon"], c["lat"]) for c in known}) < 2 or until - first + 1 < 2:
            if not day["skipped"]:
                replay_differs.append({"day": day["day"], "problems": ["Fieldwork scanned a day too early to scan"]})
            continue
        if day["skipped"]:
            replay_differs.append({"day": day["day"], "problems": ["Fieldwork skipped a day that can be scanned"]})
            continue
        daily = Scan(known, first, until, s["maxCaseShare"], s["maxTimeShare"], tie)
        best_d, where_d = daily.best(daily.case_bin, prospective=True, keep=True)
        if best_d.max() <= 0:
            if "cluster" in day:
                replay_differs.append({"day": day["day"], "problems": ["Fieldwork found a cluster; nothing scores here"]})
            continue
        top = sorted(range(len(daily.members)), key=lambda i: (-best_d[i], -where_d[i, 2], where_d[i, 0]))[0]
        got = day.get("cluster")
        a, _, c, e = where_d[top]
        problems = []
        if got is None:
            problems.append("no cluster in Fieldwork")
        else:
            if key(got["places"]) != key(daily.coords[list(daily.members[top])]):
                problems.append("different places")
            if got["start"] != dated(a) or got["end"] != day["day"] or got["observed"] != int(c):
                problems.append(f"{got['start']}..{got['end']} {got['observed']} vs {dated(a)}..{day['day']} {int(c)}")
            for name, value in (("expected", float(e)), ("llr", float(best_d[top]))):
                if abs(got[name] - value) > 1e-9:
                    problems.append(f"{name} {got[name]} != {value}")
            if got["pValue"] <= REPLAY_P_CHECKED:
                daily_max = daily.maxima(replications, rng, prospective=True)
                p_mine = (1 + int((daily_max + 1e-9 >= best_d[top]).sum())) / (1 + replications)
                ok, allowed = within(got["pValue"], p_mine, replications)
                replay_p.append({"day": day["day"], "fieldwork": got["pValue"], "here": p_mine, "allowed": round(allowed, 4), "within": ok})
                if not ok:
                    problems.append(f"p {got['pValue']} vs {p_mine}")
        if problems:
            replay_differs.append({"day": day["day"], "problems": problems})
    replay_seconds = time.perf_counter() - began
    first_here = next((p["day"] for p in replay_p if p["here"] <= 0.05), None)

    top = theirs["clusters"][0]
    return {
        "check": "46-space-time-scan",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": same_scan and not differs and not replay_differs,
        "criteria": "The same circles, runs and windows; for every cluster the same places, days, observed and expected "
                    "cases and score to 1e-9; p-values within three standard errors of the difference plus the 1/(R+1) step; "
                    "the replay's every day alike, and its p-value within that error wherever Fieldwork's is at or under 0.1",
        "totals": totals,
        "mostLikely": {"places": len(top["places"]), "start": top["start"], "end": top["end"],
                       "observed": top["observed"], "expected": round(top["expected"], 4), "pValue": top["pValue"]},
        "pValues": pvalues,
        "differs": differs,
        "replay": {"days": len(theirs["replay"]["days"]), "firstAt05InFieldwork": theirs["replay"]["firstAt"]["0.05"],
                   "firstAt05Here": first_here, "pValuesChecked": replay_p, "differs": replay_differs,
                   "seconds": round(replay_seconds, 1)},
        "shuffles": {"replications": replications, "generator": "numpy default_rng (PCG64)", "seed": NUMPY_SEED,
                     "seconds": round(seconds, 1)},
        "notEstablished": [
            "That a cluster is an outbreak: both sides compute the same statistic; neither says what it means.",
            "That the space-time permutation model suits measles in a village: it compares timing across places and "
            "cannot see where people live.",
            "That the p-values are the same to the digit: they come from different random numbers, so they agree only "
            "within Monte Carlo error. On a day near 0.05 the first day flagged can differ for that reason alone.",
            f"The replay's p-values where Fieldwork's exceed {REPLAY_P_CHECKED}: not reshuffled here, to keep the check to "
            "minutes in a browser; its clusters and scores are checked on every day.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "numpy": np.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
