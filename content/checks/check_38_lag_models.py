"""Check 38: one Fieldwork Regression fitting a model per lag, against pandas lags and one statsmodels fit per lag.

Fieldwork experiment 185 replaced seven Relate steps and seven Regressions with one of each. Relate brings a column once
per shift; Regression fits the same model once per shifted column, each on its own rows, and an adjustment can follow
the shift: the model of the temperature 2 weeks before is adjusted for the rain 2 weeks before. Here, check 37's two
municipalities and weeks, the dataset's weekly air temperature and rainfall at 0, 14 and 28 days before and 14 after.

**Independent where it matters.** pandas builds each lagged column itself, by a merge of each week with the same
municipality's week whose start date is its own plus the shift. statsmodels fits each lag on that lag's complete rows,
one indicator per municipality-year-month combination. Neither reads Fieldwork's shifted table.

Criteria, fixed before running:

1. **Each model rests on its own rows**: rows used, strata used and strata dropped equal pandas' counts for that lag's
   columns alone. And a model on the rows complete at every lag would use fewer: the fixture's rows are not those.
2. **Each coefficient** within 1e-6 relative, **each standard error** within 1e-5 relative, scaled by the Pearson
   chi-square over the residual degrees of freedom, statsmodels' `scale='X2'`, as check 37.
3. **The table names each model's shift**: its keys include `shift_days`, and each model's shift is the one declared.

What this cannot establish: that these lags, or a model per lag, are the right analysis; the intervals allow nothing for
correlation from week to week, and seven intervals are not adjusted for being seven. Nor that the dataset's temperature
and rainfall measure what a mosquito meets.

Design record: fieldwork/docs/experiments/185-one-step-for-every-lag.md
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
FIXTURE = HERE.parent / "fixtures" / "lag-models-brazil-001.json"
RESULT = HERE.parent / "results" / "check-38-lag-models.json"
TOLERANCE = {"coefficient": 1e-6, "se": 1e-5}
FIT = {"maxiter": 200, "tol": 1e-12}


def rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-300)


def lagged(frame: pandas.DataFrame, column: str, days: int) -> pandas.Series:
    """Each week's value of `column` at the same municipality's week starting `days` later, or missing."""
    right = frame[["municipio", "data_iniSE", column]].copy()
    right["data_iniSE"] = (pandas.to_datetime(right["data_iniSE"]) - pandas.Timedelta(days=int(days))).dt.strftime("%Y-%m-%d")
    right = right.rename(columns={column: "lagged"})
    return frame[["municipio", "data_iniSE"]].merge(right, on=["municipio", "data_iniSE"], how="left")["lagged"]


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    params, shifts = declared["params"], declared["shifts"]
    frame = pandas.DataFrame(fixture["input"]["rows"])
    for c in ["casos", "tempmed", "precip_total_semana"]:
        frame[c] = pandas.to_numeric(frame[c].replace("", None))
    strata = params["strata"]
    frame["stratum"] = frame[strata].astype(str).agg("\u001f".join, axis=1)
    columns = {}
    for d in shifts:
        columns[d] = (f"t{d}", f"r{d}")
        frame[f"t{d}"] = lagged(frame, "tempmed", d).to_numpy()
        frame[f"r{d}"] = lagged(frame, "precip_total_semana", d).to_numpy()
    every = frame.dropna(subset=["casos", *[c for pair in columns.values() for c in pair]])
    comparisons = []
    for model in fixture["output"]["models"]:
        d = model["shiftDays"]
        t, r = columns[d]
        used = frame.dropna(subset=["casos", t, r])
        totals = used.groupby("stratum")["casos"].transform("sum")
        fitted = used[totals > 0].reset_index(drop=True)
        design = pandas.concat([fitted[[t, r]].astype(float),
                                pandas.get_dummies(fitted["stratum"], prefix="s", dtype=float)], axis=1)
        result = sm.GLM(fitted["casos"].astype(float), design, family=sm.families.Poisson()).fit(scale="X2", **FIT)
        own = {model["column"]: t, model["rain"]: r}
        estimates = []
        for e in model["estimates"]:
            name = own[e["column"]]
            checks = {"coefficient": bool(rel(e["coefficient"], result.params[name]) < TOLERANCE["coefficient"]),
                      "se": bool(rel(e["se"], result.bse[name]) < TOLERANCE["se"])}
            estimates.append({"term": e["term"], "coefficient": [e["coefficient"], float(result.params[name])],
                              "se": [e["se"], float(result.bse[name])], "checks": checks,
                              "agrees": all(checks.values())})
        counts = {"rowsUsed": [model["rows"]["used"], int(len(used))],
                  "strataUsed": [model["strata"]["used"], int(fitted["stratum"].nunique())],
                  "strataDropped": [model["strata"]["dropped"], int(used.loc[totals == 0, "stratum"].nunique())]}
        own_rows = bool(model["rows"]["used"] > len(every))
        comparisons.append({"column": model["column"], "shiftDays": d, "rain": model["rain"], "counts": counts,
                            "rowsCompleteAtEveryLag": int(len(every)), "restsOnItsOwnRows": own_rows,
                            "estimates": estimates, "dispersion": [model["dispersion"], float(result.scale)],
                            "agrees": all(a == b for a, b in counts.values()) and own_rows
                            and all(e["agrees"] for e in estimates)})
    keys = fixture["output"]["tableKeys"]
    shift_named = bool("shift_days" in keys and [m["shiftDays"] for m in fixture["output"]["models"]] == shifts)
    return {
        "check": "38-lag-models",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {"runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
                        "isPyodide": sys.platform == "emscripten", "pandas": pandas.__version__,
                        "numpy": numpy.__version__, "statsmodels": statsmodels.__version__},
        "fixture": {"id": fixture["fixtureId"], "sha256": digest, "application": fixture["application"],
                    "operation": fixture["operation"]},
        "criterion": {"rows": "each model's rows, strata used and dropped equal pandas' for that lag alone, and exceed "
                              "the rows complete at every lag",
                      "coefficient": f"relative difference below {TOLERANCE['coefficient']}",
                      "se": f"relative difference below {TOLERANCE['se']}, Pearson-scaled",
                      "table": "the keys include shift_days and each model carries its declared shift"},
        "comparisons": comparisons,
        "table": {"keys": keys, "shiftNamed": shift_named},
        "notEstablished": [
            "That these lags, or one model per lag, are the right analysis; the intervals allow nothing for correlation "
            "from week to week, and none is adjusted for the number of lags.",
            "That tempmed and precip_total_semana measure what a mosquito meets: the first is InfoDengue's, the second "
            "CHIRPS at one grid cell.",
        ],
        "agrees": shift_named and all(c["agrees"] for c in comparisons),
    }


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for c in result["comparisons"]:
        print(f"{'OK ' if c['agrees'] else 'DIFF'} {c['column']} with {c['rain']}: rows {c['counts']['rowsUsed']}"
              f" (every lag: {c['rowsCompleteAtEveryLag']}), strata {c['counts']['strataUsed']},"
              f" dropped {c['counts']['strataDropped']}")
        for e in c["estimates"]:
            print(f"     {'OK ' if e['agrees'] else 'DIFF'} {e['term']}: coefficient {e['coefficient'][0]:.10g} /"
                  f" {e['coefficient'][1]:.10g}, se {e['se'][0]:.8g} / {e['se'][1]:.8g}")
    print(f"table keys {result['table']['keys']}, shift named: {result['table']['shiftNamed']}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
