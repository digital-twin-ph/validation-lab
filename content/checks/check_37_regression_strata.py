"""Check 37: Fieldwork Regression with several strata columns, against statsmodels with one indicator per stratum.

Fieldwork experiment 182 widened the Brazil dengue models to sixteen years, comparing weeks only within the same
municipality, year and month. Regression gained strata over several columns taken together. Here, six municipalities of
Rio de Janeiro state, 2010 to 2025, the twelve doubled year-edge weeks left out: weekly cases on the dataset's weekly air
temperature, adjusted for its weekly rainfall, overdispersed errors.

**Independent where it matters.** Fieldwork absorbs the strata in a conditional Poisson likelihood; statsmodels fits
one indicator column per municipality-year-month combination, which gives the same slopes. The combination is built
here with pandas from the three columns, not from Fieldwork's key.

Criteria, fixed before running:

1. **The same rows and strata**: rows with every model column present, strata with at least one case; the count of
   strata dropped for having none.
2. **Each coefficient** within 1e-6 relative, **each standard error** within 1e-5 relative. The standard error is
   scaled by the Pearson chi-square over the residual degrees of freedom, statsmodels' `scale='X2'`.

What this cannot establish: that these strata are the right comparison, or that the dataset's temperature and rainfall
measure what a mosquito meets. tempmed is InfoDengue's; precip_total_semana is CHIRPS at one grid cell.

Design record: fieldwork/docs/experiments/182-brazil-across-years.md
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

import numpy
import pandas
import statsmodels
import statsmodels.api as sm
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "regression-strata-brazil-001.json"
RESULT = HERE.parent / "results" / "check-37-regression-strata.json"
TOLERANCE = {"coefficient": 1e-6, "se": 1e-5}
FIT = {"maxiter": 200, "tol": 1e-12}


def rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-300)


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    params = fixture["declaredParameters"]["params"]
    frame = pandas.DataFrame(fixture["input"]["rows"])
    model_columns = [params["outcome"], params["exposure"]["column"], *[a["column"] for a in params["adjust"]]]
    for c in model_columns:
        frame[c] = pandas.to_numeric(frame[c].replace("", None))
    comparisons = []
    for case in fixture["output"]["cases"]:
        strata = case["strataColumns"]
        used = frame.dropna(subset=model_columns).copy()
        for c in strata:
            used = used[used[c].astype(str) != ""]
        used["stratum"] = used[strata].astype(str).agg("\u001f".join, axis=1)
        totals = used.groupby("stratum")[params["outcome"]].transform("sum")
        dropped = int(used.loc[totals == 0, "stratum"].nunique())
        fitted = used[totals > 0].reset_index(drop=True)
        terms = [params["exposure"]["column"], *[a["column"] for a in params["adjust"]]]
        design = pandas.concat([fitted[terms].astype(float),
                                pandas.get_dummies(fitted["stratum"], prefix="s", dtype=float)], axis=1)
        result = sm.GLM(fitted[params["outcome"]].astype(float), design, family=sm.families.Poisson()).fit(scale="X2", **FIT)
        estimates = []
        for e in case["estimates"]:
            checks = {"coefficient": bool(rel(e["coefficient"], result.params[e["column"]]) < TOLERANCE["coefficient"]),
                      "se": bool(rel(e["se"], result.bse[e["column"]]) < TOLERANCE["se"])}
            estimates.append({"term": e["term"], "coefficient": [e["coefficient"], float(result.params[e["column"]])],
                              "se": [e["se"], float(result.bse[e["column"]])], "checks": checks, "agrees": all(checks.values())})
        counts = {"rowsUsed": [case["rows"]["used"], int(len(used))],
                  "strataUsed": [case["strata"]["used"], int(fitted["stratum"].nunique())],
                  "strataDropped": [case["strata"]["dropped"], dropped]}
        same = bool(all(a == b for a, b in counts.values()))
        comparisons.append({"note": case["note"], "strataColumns": strata, "counts": counts, "estimates": estimates,
                            "dispersion": [case["dispersion"], float(result.scale)],
                            "agrees": same and all(e["agrees"] for e in estimates)})
    return {
        "check": "37-regression-strata",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {"runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
                        "isPyodide": sys.platform == "emscripten", "pandas": pandas.__version__,
                        "numpy": numpy.__version__, "statsmodels": statsmodels.__version__},
        "fixture": {"id": fixture["fixtureId"], "sha256": digest, "application": fixture["application"],
                    "operation": fixture["operation"]},
        "criterion": {"counts": "the same rows used, strata used and strata dropped",
                      "coefficient": f"relative difference below {TOLERANCE['coefficient']}",
                      "se": f"relative difference below {TOLERANCE['se']}, Pearson-scaled"},
        "comparisons": comparisons,
        "notEstablished": [
            "That municipality, year and month are the right comparison for these data.",
            "That tempmed and precip_total_semana measure what a mosquito meets: the first is InfoDengue's, the second "
            "CHIRPS at one grid cell, summed over ISO weeks with missing days as 0.",
        ],
        "agrees": all(c["agrees"] for c in comparisons),
    }


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for c in result["comparisons"]:
        print(f"{'OK ' if c['agrees'] else 'DIFF'} {c['note']}: rows {c['counts']['rowsUsed']}, strata {c['counts']['strataUsed']}, dropped {c['counts']['strataDropped']}")
        for e in c["estimates"]:
            print(f"     {'OK ' if e['agrees'] else 'DIFF'} {e['term']}: coefficient {e['coefficient'][0]:.10g} / {e['coefficient'][1]:.10g}, se {e['se'][0]:.8g} / {e['se'][1]:.8g}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
