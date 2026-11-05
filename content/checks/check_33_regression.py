"""Check 33: Fieldwork Regression against statsmodels, on two published models.

Two fixtures, the two worked examples the widget was built to reproduce (Fieldwork experiment 167):

- **Salmonella**, Germany 2021: logistic regression of case status on Galia melon in April, adjusted for age group
  (seven groups) and sex, against two control groups, with likelihood-ratio (profile) intervals as published. The
  rows are CC BY 4.0 and travel in the fixture.
- **NYC**, 2016 to 2025: Poisson regression of daily child asthma emergency visits on ozone, adjusted for PM2.5, NO2,
  a temperature spline and holidays, with 840 strata, and HAC (Newey-West) errors. The counts are the city health
  department's and are not redistributed: the fixture names the authors' Zenodo package and its digest, and this
  check fetches it.

**Genuinely independent.** statsmodels fits each model with its own IRLS, builds the spline with patsy's `bs`, and
computes the HAC covariance itself. Fieldwork's fit is a Rust kernel; nothing is shared but the declared model. The
strata are fitted here as fixed effects (one indicator per stratum), which gives the same slopes as the conditional
likelihood Fieldwork uses: a different route to the same estimator.

**Profile intervals are computed here**, because statsmodels does not provide them for a GLM: each limit is found by
refitting statsmodels' model with the coefficient held fixed through an offset, and bisecting on where the deviance
has risen by z^2. The arithmetic is this check's, the fits are statsmodels'.

Criteria, fixed before running:

1. **Coefficients** agree to a relative difference below 1e-6, for every reported term.
2. **Model-based standard errors** agree below 1e-6.
3. **Profile limits** agree below 1e-4 (each is a root found by bisection on both sides).
4. **HAC standard errors** agree below 1e-6 with statsmodels' Newey-West at 14 lags without small-sample correction,
   on the stratum fixed-effects model. And the ozone coefficient and HAC standard error equal the authors' archived R
   result below 1e-9.
5. **Rows**: the same number used.

**Amended after the first run, 2026-11-05, and recorded as such.** (a) statsmodels is fitted to a deviance tolerance of
1e-12: at its default of 1e-8 it stopped Salmonella one iteration early, and its standard error for Galia melon differed
from Fieldwork's by 4e-6; tightened, it equals Fieldwork's to 15 digits. (b) A term whose standard error exceeds 1,000
on the log scale is **separated**: no finite estimate exists, and two implementations stop at different points along
the same ridge. Such a term is compared only on being separated in both, and listed. The panel case's age group 80+ is
one, and Fieldwork reports it as an odds ratio with no warning, which is a finding against Fieldwork.

What this cannot establish: that either model is well specified, or that its estimate is causal.

Design record: fieldwork/docs/experiments/167-regression.md
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import pathlib
import platform
import sys
from datetime import datetime, timezone

import numpy
import pandas
import patsy
import statsmodels
import statsmodels.api as sm
import statsmodels.formula.api as smf
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures"
RESULT = HERE.parent / "results" / "check-33-regression.json"
Z = 1.959963984540054
TOLERANCE = {"coefficient": 1e-6, "se": 1e-6, "profile": 1e-4, "hac": 1e-6, "authors": 1e-9}
FIT = {"tol": 1e-12, "maxiter": 200}
SEPARATED_SE = 1000.0


def rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-300)


def kind_of(errors_text: str) -> str:
    return "profile" if errors_text.startswith("likelihood-ratio") else "hac" if errors_text.startswith("HAC") else "wald"


# Fieldwork names terms as R does: `galiamelo_apr21`, `age_group710-14`. patsy names them `C(galiamelo_apr2)[T.1]`.
def patsy_name(term: str, column: str, kind: str) -> str:
    if kind == "categorical":
        return f"C({column})[T.{term[len(column):]}]"
    return column


# ---- Salmonella ----------------------------------------------------------------------------------------------------

def _profile_limit(y, X, j, beta_hat, deviance_hat, direction):
    """Where the deviance, refitted with coefficient j held at b, has risen by z^2 -- R's confint() for a GLM."""
    others = numpy.delete(X, j, axis=1)
    target = deviance_hat + Z * Z

    def deviance_at(b):
        fit = sm.GLM(y, others, family=sm.families.Binomial(), offset=b * X[:, j]).fit(**FIT)
        return fit.deviance

    step = 0.5
    inner, outer = beta_hat, beta_hat + direction * step
    for _ in range(60):
        if deviance_at(outer) > target:
            break
        inner, step = outer, step * 2
        outer = beta_hat + direction * step
    for _ in range(100):
        mid = (inner + outer) / 2
        if deviance_at(mid) > target:
            outer = mid
        else:
            inner = mid
        if abs(outer - inner) < 1e-10:
            break
    return math.exp((inner + outer) / 2)


def salmonella(fixture: dict) -> list[dict]:
    params = fixture["declaredParameters"]["params"]
    kinds = {params["exposure"]["column"]: params["exposure"]["as"], **{t["column"]: t["as"] for t in params["adjust"]}}
    out = []
    for case in fixture["output"]["cases"]:
        frame = pandas.DataFrame(fixture["input"][case["rowsFrom"]]["rows"])
        frame = frame[frame["fall"].isin(["1", "0"])].copy()
        frame["y"] = (frame["fall"] == "1").astype(float)
        model = smf.glm("y ~ C(galiamelo_apr2) + C(age_group7) + C(sex)", data=frame, family=sm.families.Binomial())
        fit = model.fit(**FIT)
        kind = kind_of(case["errors"])
        X, names = model.exog, model.exog_names
        terms = []
        for e in case["estimates"]:
            name = patsy_name(e["term"], e["column"], kinds[e["column"]])
            j = names.index(name)
            row = {"term": e["term"], "statsmodelsTerm": name,
                   "coefficient": [e["coefficient"], float(fit.params.iloc[j])],
                   "se": [e["se"], float(fit.bse.iloc[j])]}
            if e["se"] > SEPARATED_SE or fit.bse.iloc[j] > SEPARATED_SE:
                both = bool(e["se"] > SEPARATED_SE and fit.bse.iloc[j] > SEPARATED_SE)
                row.update({"separated": True, "checks": {"separatedInBoth": both}, "agrees": both,
                            "fieldworkReported": {"ratio": e["ratio"], "lower": e["lower"], "upper": e["upper"]}})
                terms.append(row)
                continue
            checks = {"coefficient": bool(rel(e["coefficient"], fit.params.iloc[j]) < TOLERANCE["coefficient"]),
                      "se": bool(rel(e["se"], fit.bse.iloc[j]) < TOLERANCE["se"])}
            if kind == "profile":
                lower = _profile_limit(model.endog, X, j, fit.params.iloc[j], fit.deviance, -1)
                upper = _profile_limit(model.endog, X, j, fit.params.iloc[j], fit.deviance, 1)
                row["profile"] = {"fieldwork": [e["lower"], e["upper"]], "here": [lower, upper]}
                checks["profile"] = rel(e["lower"], lower) < TOLERANCE["profile"] and rel(e["upper"], upper) < TOLERANCE["profile"]
            row["checks"] = checks
            row["agrees"] = all(checks.values())
            terms.append(row)
        out.append({"fixture": "salmonella", "note": case["note"], "errors": kind,
                    "rows": {"fieldwork": case["rows"]["used"], "statsmodels": int(fit.nobs)},
                    "terms": terms,
                    "agrees": all(t["agrees"] for t in terms) and case["rows"]["used"] == int(fit.nobs)})
    return out


# ---- NYC -----------------------------------------------------------------------------------------------------------

def _nyc_frame(fixture: dict) -> pandas.DataFrame:
    sys.path.insert(0, str(HERE.parents[1] / "scripts"))
    from remote_zip import HttpRangeFile  # noqa: E402  the lab's own range reader, for Zenodo
    import zipfile
    remote = fixture["input"]["remote"]
    with zipfile.ZipFile(io.BufferedReader(HttpRangeFile(remote["url"]))) as archive:
        data = archive.read(remote["entry"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != remote["sha256"]:
        raise SystemExit(f"The fetched member's digest is {digest}, not the fixture's {remote['sha256']}.")
    frame = pandas.read_csv(io.BytesIO(data), na_values=["NA"], keep_default_na=True, dtype={"stratum": str})
    return frame.sort_values("date", kind="stable").reset_index(drop=True)


def nyc(fixture: dict) -> list[dict]:
    params = fixture["declaredParameters"]["params"]
    frame = _nyc_frame(fixture)
    used = frame.dropna(subset=fixture["input"]["columns"]).copy()
    # A stratum with no events carries no information in the conditional model, and its fixed effect has no finite MLE.
    totals = used.groupby("stratum")["count"].transform("sum")
    dropped_strata = int(used.loc[totals == 0, "stratum"].nunique())
    fitted_rows = used[totals > 0].reset_index(drop=True)
    formula = ("count ~ 0 + o3_lag02_10 + pm25_lag02_10 + no2_lag02_10 + bs(tmean_lag03, df=4) + holiday + C(stratum)")
    # The spline's knots come from every used row, as Fieldwork's do, not only from the strata with events.
    basis = patsy.dmatrix("bs(tmean_lag03, df=4) - 1", used, return_type="dataframe")
    knots_from = patsy.build_design_matrices([basis.design_info], fitted_rows, return_type="dataframe")[0]
    design = pandas.concat([fitted_rows[["o3_lag02_10", "pm25_lag02_10", "no2_lag02_10"]], knots_from,
                            fitted_rows[["holiday"]], pandas.get_dummies(fitted_rows["stratum"], prefix="s", dtype=float)], axis=1)
    model = sm.GLM(fitted_rows["count"], design, family=sm.families.Poisson())
    plain = model.fit(**FIT)
    hac = model.fit(cov_type="HAC", cov_kwds={"maxlags": params["hacLag"], "use_correction": False}, **FIT)
    out = []
    for case in fixture["output"]["cases"]:
        kind = kind_of(case["errors"])
        reference = hac if kind == "hac" else plain
        terms = []
        for e in case["estimates"]:
            name = e["column"]
            checks = {"coefficient": rel(e["coefficient"], reference.params[name]) < TOLERANCE["coefficient"],
                      "se": rel(e["se"], reference.bse[name]) < TOLERANCE["hac" if kind == "hac" else "se"]}
            terms.append({"term": e["term"], "coefficient": [e["coefficient"], float(reference.params[name])],
                          "se": [e["se"], float(reference.bse[name])], "checks": checks, "agrees": all(checks.values())})
        row = {"fixture": "nyc", "note": case["note"], "errors": kind,
               "rows": {"fieldwork": case["rows"]["used"], "statsmodels": int(len(used))},
               "strata": {"fieldwork": case["strata"], "here": {"used": int(fitted_rows["stratum"].nunique()), "dropped": dropped_strata}},
               "terms": terms}
        agrees = all(t["agrees"] for t in terms) and case["rows"]["used"] == len(used)
        if kind == "hac":
            authors = fixture["declaredParameters"]["authorsArchivedR"]
            ozone = next(e for e in case["estimates"] if e["column"] == "o3_lag02_10")
            row["authorsArchivedR"] = {"coefficient": [ozone["coefficient"], authors["coefficient"]],
                                       "se": [ozone["se"], authors["se"]],
                                       "agrees": rel(ozone["coefficient"], authors["coefficient"]) < TOLERANCE["authors"]
                                       and rel(ozone["se"], authors["se"]) < TOLERANCE["authors"]}
            agrees = agrees and row["authorsArchivedR"]["agrees"]
        row["agrees"] = agrees
        out.append(row)
    return out


def run() -> dict:
    s_fixture, s_digest = load_fixture(FIXTURES / "regression-salmonella-001.json")
    n_fixture, n_digest = load_fixture(FIXTURES / "regression-nyc-001.json")
    comparisons = salmonella(s_fixture) + nyc(n_fixture)
    return {
        "check": "33-regression",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "statsmodels": statsmodels.__version__, "patsy": patsy.__version__,
            "pandas": pandas.__version__, "numpy": numpy.__version__,
        },
        "fixtures": [{"id": f["fixtureId"], "sha256": d, "application": f["application"], "operation": f["operation"]}
                     for f, d in ((s_fixture, s_digest), (n_fixture, n_digest))],
        "criterion": {"coefficient": f"relative difference below {TOLERANCE['coefficient']}",
                      "se": f"relative difference below {TOLERANCE['se']}",
                      "profile": f"both limits, relative difference below {TOLERANCE['profile']}",
                      "hac": f"relative difference below {TOLERANCE['hac']}, Newey-West 14 lags without correction",
                      "authors": f"the authors' archived R coefficient and HAC standard error, below {TOLERANCE['authors']}"},
        "comparisons": comparisons,
        "notEstablished": [
            "That either model is well specified, or that an adjusted estimate is causal.",
            "Pyodide: this run is CPython. The NYC fixture fetches its data from Zenodo, which the browser kernel may not reach.",
            "Offsets, overdispersed errors and wider categorical exposures: neither example uses them.",
            "Separated terms: only that both implementations find them separated. Fieldwork reports them as ordinary odds "
            "ratios with no warning (the panel case's 80+ age group), which this check records and does not excuse.",
        ],
        "agrees": all(c["agrees"] for c in comparisons),
    }


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2, default=lambda o: o.item()) + "\n", encoding="utf-8")
    for c in result["comparisons"]:
        worst = max(max(rel(*t["coefficient"]), rel(*t["se"])) for t in c["terms"] if not t.get("separated"))
        for t in c["terms"]:
            if t.get("separated"):
                print(f"     separated: {t['term']}, standard errors {t['se'][0]:.0f} and {t['se'][1]:.0f}; Fieldwork reported "
                      f"{t['fieldworkReported']['ratio']:.3g} ({t['fieldworkReported']['lower']:.3g} to {t['fieldworkReported']['upper']:.3g})")
        print(f"{'OK ' if c['agrees'] else 'DIFF'} {c['fixture']:<10} {c['errors']:<8} rows {c['rows']['fieldwork']}/{c['rows']['statsmodels']}"
              f"  worst relative difference {worst:.1e}  {c['note']}")
        for t in c["terms"]:
            if not t["agrees"]:
                print(f"       {t['term']}: {t['checks']}  coef {t['coefficient']}  se {t['se']}" + (f"  profile {t.get('profile')}" if 'profile' in t else ''))
        if "authorsArchivedR" in c:
            print(f"     authors' R: {c['authorsArchivedR']}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
