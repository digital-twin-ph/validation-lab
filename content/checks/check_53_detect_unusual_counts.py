"""Check 53: Fieldwork's Detect unusual counts, on four series, against EARS, CUSUM and EWMA written again in numpy.

Fieldwork experiment 228: Detect unusual counts holds each period of a series of counts to a threshold set from the
series' own past, by EARS C1, C2 or C3 (Hutwagner and others, J Urban Health 2003, open at PubMed Central), CUSUM
(Page, Biometrika 1954) or EWMA (Roberts, Technometrics 1959). The fixture is Fieldwork's own output on four series:

- **made-up-40**: 40 made-up days with five days of excess (days 25 to 29), the series Fieldwork's unit test holds to
  R's `surveillance` 1.25.0; R's values travel with it, so this check is a third reading of the same days.
- **syndromic-gi-2026**: the gastrointestinal visits per day in the syndromic worked example, by the syndrome each visit
  was generated as, 175 days with a seeded outbreak, 13 to 22 April.
- **seasonal-weekly**: three made-up years of weekly counts with a winter peak each year: what a method without a
  seasonal baseline does with a season.
- **sparse-daily**: a made-up rare condition, most days 0, with a cluster: baselines that do not vary, and a baseline
  whose mean is 0.

**Independent.** Each method is written here from its published definition and the conventions the fixture declares
(its `declaredParameters`), with numpy for the arithmetic and scipy for the normal quantile. Nothing of Fieldwork's
code is read.

Criteria, fixed before running:

1. **The same periods computed**: a value where Fieldwork has one, none where it has none, for every measure.
2. **The same numbers**: expected, threshold, statistic and limit within 1e-6 of each other, relative where above 1:
   Fieldwork's normal quantile refines an approximation and agrees with scipy's to about 1e-7.
3. **The same signals**, except on a period whose statistic lies within that tolerance of its limit, which is
   listed and not counted against.
4. **The same refusals**: where Fieldwork will not compute (a baseline whose mean is 0 for CUSUM, one that does not vary
   for EWMA), neither does this.
5. **Against R**, on made-up-40, read from R's recorded values: EARS C1 and C2 thresholds within 1e-6, CUSUM's the same;
   EARS C3 is reported, not judged, because R leaves the current day out of C3 and the paper does not.

What this cannot establish: that a signal is an outbreak, or that any α, h or L suits a surveillance system. Both
sides compute the same statistic from the same declared baseline; neither says what it means. Nor does it check a
seasonal baseline (Farrington), which Fieldwork does not have.

Design record: fieldwork/docs/experiments/228-detect-unusual-counts.md
"""
from __future__ import annotations

import json
import math
import pathlib
import platform
import sys
from datetime import datetime, timezone

import numpy as np
from scipy.stats import norm

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "detect-unusual-counts-001.json"
RESULT = HERE.parent / "results" / "check-53-detect-unusual-counts.json"
TOLERANCE = 1e-6
MEASURES = ("expected", "threshold", "statistic", "limit")
DEFAULTS = {"baseline": 7, "alphaC12": 0.001, "alphaC3": 0.025, "minSigma": 0.0, "baselinePeriods": 7,
            "k": 1.04, "h": 2.26, "lambda": 0.3, "L": 3.0, "reset": False}


class Refused(Exception):
    """The method cannot be computed on this series, as declared."""


def blank(x):
    return {"observed": x, "expected": None, "threshold": None, "statistic": None, "limit": None, "signal": None}


def ears(counts: np.ndarray, method: str, s: dict) -> list[dict]:
    """EARS (Hutwagner 2003). C1: the mean and sample standard deviation of the 7 periods before; C2: of the 7 before a
    guard of 2; C3: over the period and the 2 before, the sum of how far each C2 statistic exceeds 1."""
    lag = 1 if method == "ears-c1" else 3
    alpha = s["alpha"] if s.get("alpha") is not None else (DEFAULTS["alphaC3"] if method == "ears-c3" else DEFAULTS["alphaC12"])
    z = norm.ppf(1 - alpha)
    n, b = len(counts), s["baseline"]

    def c2(t):
        if t - lag - b + 1 < 0:
            return None
        window = counts[t - lag - b + 1: t - lag + 1]
        mu, sig = window.mean(), max(window.std(ddof=1), s["minSigma"])
        return {"mean": mu, "sig": sig, "stat": (counts[t] - mu) / sig if sig > 0 else None}

    rows = []
    for t in range(n):
        x, here = counts[t], c2(t)
        if here is None:
            rows.append(blank(x))
            continue
        if method != "ears-c3":
            threshold = here["mean"] + z * here["sig"]
            rows.append({"observed": x, "expected": here["mean"], "threshold": threshold, "statistic": here["stat"],
                         "limit": z, "signal": x > threshold if here["sig"] > 0 else x > here["mean"]})
            continue
        before = [c2(t - 2), c2(t - 1)]
        if any(p is None or p["stat"] is None for p in before) or here["stat"] is None:
            rows.append({**blank(x), "expected": here["mean"]})
            continue
        carried = sum(max(0.0, p["stat"] - 1) for p in before)
        c3 = carried + max(0.0, here["stat"] - 1)
        # The count that brings C3 to z: past z already from the two before, any count does.
        threshold = 0.0 if carried > z else max(0.0, here["mean"] + here["sig"] * (1 + z - carried))
        rows.append({"observed": x, "expected": here["mean"], "threshold": threshold, "statistic": c3, "limit": z,
                     "signal": c3 > z})
    return rows


def cusum(counts: np.ndarray, s: dict) -> list[dict]:
    """Page's upper CUSUM on counts standardized by the baseline's mean, as for Poisson counts:
    S(t) = max(0, S(t-1) + (x - m)/sqrt(m) - k), signalling when S reaches h; m the mean of the first periods."""
    p = s["baselinePeriods"]
    if len(counts) <= p:
        raise Refused("a baseline that leaves no period to watch")
    m = counts[:p].mean()
    if not m > 0:
        raise Refused("a baseline whose mean is 0")
    rows, S = [], 0.0
    for t, x in enumerate(counts):
        if t < p:
            rows.append({**blank(x), "expected": m})
            continue
        previous = S
        S = max(0.0, S + (x - m) / math.sqrt(m) - s["k"])
        signal = S >= s["h"]
        # The least whole count that would have brought S to h from where it stood.
        threshold = max(0, math.ceil(m + math.sqrt(m) * (s["h"] + s["k"] - previous)))
        rows.append({"observed": x, "expected": m, "threshold": threshold, "statistic": S, "limit": s["h"],
                     "signal": signal})
        if signal and s["reset"]:
            S = 0.0
    return rows


def ewma(counts: np.ndarray, s: dict) -> list[dict]:
    """Roberts' EWMA: Z(i) = lambda x + (1 - lambda) Z(i-1), from Z(0) the baseline's mean m, held to
    m + L sigma sqrt(lambda/(2 - lambda) (1 - (1 - lambda)^(2i))), sigma the baseline's sample standard deviation."""
    p, lam, L = s["baselinePeriods"], s["lambda"], s["L"]
    if len(counts) <= p:
        raise Refused("a baseline that leaves no period to watch")
    base = counts[:p]
    m, sigma = base.mean(), base.std(ddof=1)
    if not sigma > 0:
        raise Refused("a baseline that does not vary")
    rows, Z = [], m
    for t, x in enumerate(counts):
        if t < p:
            rows.append({**blank(x), "expected": m})
            continue
        i = t - p + 1
        Z = lam * x + (1 - lam) * Z
        limit = m + L * sigma * math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * i)))
        rows.append({"observed": x, "expected": m, "threshold": limit, "statistic": Z, "limit": limit,
                     "signal": Z > limit})
    return rows


def compute(counts: list[float], settings: dict) -> list[dict]:
    s = {**DEFAULTS, **settings}
    x = np.asarray(counts, dtype=float)
    if settings["method"].startswith("ears"):
        return ears(x, settings["method"], s)
    return cusum(x, s) if settings["method"] == "cusum" else ewma(x, s)


def close(a, b) -> bool:
    return abs(a - b) <= TOLERANCE * max(1.0, abs(a), abs(b))


def compare(series: dict, run: dict) -> dict:
    """One method on one series: every period, every measure."""
    label = f"{series['id']} · {run['settings']['method']}" + (f" ({run['label']})" if run.get("label") else "")
    try:
        here = compute(series["counts"], run["settings"])
    except Refused as why:
        agrees = "refused" in run
        return {"run": label, "agrees": agrees, "refused": {"fieldwork": run.get("refused"), "here": str(why)},
                "differs": [] if agrees else [f"refused here ({why}); Fieldwork computed it"]}
    if "refused" in run:
        return {"run": label, "agrees": False, "differs": [f"Fieldwork refused ({run['refused']}); computed here"]}
    differs, near, signals, largest = [], [], 0, 0.0
    for t, (f, h) in enumerate(zip(run["rows"], here)):
        period = series["periods"][t]
        for key in MEASURES:
            a, b = f[key], h[key]
            if (a is None) != (b is None):
                differs.append(f"{period} {key}: {a} in Fieldwork, {b} here")
            elif a is not None:
                largest = max(largest, abs(a - b) / max(1.0, abs(a), abs(b)))
                if not close(a, b):
                    differs.append(f"{period} {key}: {a!r} in Fieldwork, {b!r} here")
        fs, hs = f["signal"], h["signal"]
        hs = None if hs is None else bool(hs)
        if fs:
            signals += 1
        if fs != hs:
            if h["statistic"] is not None and f["limit"] is not None and close(h["statistic"], f["limit"]):
                near.append(f"{period}: statistic {h['statistic']!r} at its limit {f['limit']!r}")
            else:
                differs.append(f"{period} signal: {fs} in Fieldwork, {hs} here")
    if len(run["rows"]) != len(here):
        differs.append(f"{len(run['rows'])} periods in Fieldwork, {len(here)} here")
    return {"run": label, "agrees": not differs, "periods": len(here), "signals": signals,
            "largestRelativeDifference": largest, "atTheLimit": near, "differs": differs}


def against_r(series: dict, r: dict) -> dict:
    """made-up-40 read a third time, from R's recorded values: R watches the last periods of the series, as many as it
    gives values for (`range` counts them from 1); `upper` its bound, `alarm` its signal. C3 is reported, not judged.
    Signals are named by their period."""
    out = {}
    for method, key in (("ears-c1", "C1"), ("ears-c2", "C2"), ("ears-c3", "C3"), ("cusum", "cusum")):
        settings = {"method": method, **({"baselinePeriods": 7} if method == "cusum" else {})}
        here = compute(series["counts"], settings)
        rec = r[key]
        first = len(series["counts"]) - len(rec["upper"])
        days = list(range(first + 1, len(series["counts"]) + 1))
        diff = [abs(here[d - 1]["threshold"] - u) for d, u in zip(days, rec["upper"])
                if here[d - 1]["threshold"] is not None and u is not None]
        days_here = [d for d in days if here[d - 1]["signal"]]
        days_r = [d for d, a in zip(days, rec["alarm"]) if a]
        largest = max(diff) if diff else None
        name = lambda ds: [series["periods"][d - 1] for d in ds]
        out[method] = {"largestThresholdDifference": largest, "signals": {"here": name(days_here), "R": name(days_r)},
                       "judged": method != "ears-c3"}
        if method != "ears-c3":
            out[method]["agrees"] = days_here == days_r and (largest or 0) <= TOLERANCE
    return out


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    results = [compare(series, r) for series in fixture["series"] for r in series["runs"]]
    made_up = next(s for s in fixture["series"] if s["id"] == "made-up-40")
    r = against_r(made_up, fixture["rReference"])
    agrees = all(x["agrees"] for x in results) and all(v["agrees"] for v in r.values() if v["judged"])
    report = {
        "check": "53-detect-unusual-counts",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest, "application": fixture["application"],
                    "operation": fixture["operation"]},
        "agrees": agrees,
        "criteria": ["the same periods computed", f"the same numbers, within {TOLERANCE}",
                     "the same signals, except at the limit, listed", "the same refusals",
                     "against R on made-up-40: C1, C2 thresholds and CUSUM; C3 reported"],
        "runs": results,
        "againstR": r,
        "series": [{"id": s["id"], "periods": len(s["counts"]), "total": sum(s["counts"]), "about": s["description"]}
                   for s in fixture["series"]],
        "notEstablished": [
            "That a signal is an outbreak: both sides compute the same statistic from the same baseline.",
            "That any alpha, h or L suits a surveillance system: they are decisions about false alarms.",
            "A seasonal baseline (Farrington, or a GLM): Fieldwork has none, and seasonal-weekly shows what follows.",
            "Fieldwork's reading of a table into a series (periods put in order, a missing period counted as 0): the "
            "fixture carries the series as Fieldwork read them, so that step is checked by Fieldwork's own tests.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "numpy": np.__version__, "scipy": __import__("scipy").__version__,
                        "pyodide": "pyodide" in sys.modules},
    }
    try:
        RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return report


if __name__ == "__main__":
    out = run()
    print("agrees:", out["agrees"])
    for x in out["runs"]:
        print(("  ok  " if x["agrees"] else "  NO  ") + x["run"], x.get("signals", ""), x["differs"][:3])
    print(json.dumps(out["againstR"], indent=1))
