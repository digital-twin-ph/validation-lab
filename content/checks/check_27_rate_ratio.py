"""Check 27: Fieldwork Rate ratio with an interval against statsmodels.

A ratio of two rates and a 95% interval, over John Snow's 1855 figures: deaths among houses
supplied by two water companies, and deaths among the people of sub-districts grouped by the
supply their published table declares.

**Why this widget and why now.** It is the epidemiological claim the South London example is
built to make -- an epidemiologist reading that figure will check the ratio against their own
calculation before they trust anything else on the screen -- and it carried no independent
evidence at all. Every number in it rested on this project's own tests.

**Genuinely independent.** `statsmodels.stats.rates.confint_poisson_2indep` is a separate
implementation by separate authors of the same estimator, and the estimator matters here: a rate
ratio is NOT a risk ratio. Fieldwork states `ln(RR) ± z·sqrt(1/a + 1/b)`, which is the Poisson
interval over event counts; a risk ratio over the same table uses
`sqrt(1/a - 1/n1 + 1/b - 1/n2)` and gives different bounds. Comparing against the wrong one would
have produced a confident disagreement about nothing. `method='wald-log'` is the one Fieldwork
declares. The `score` method (W2A) is carried as a third opinion: a different statistic with its
variance estimated under the null rather than from the observed rates, so the distance between
the two is what the declared choice costs. `exact-cond` was wanted for that role and statsmodels
documents it as NOT YET implemented, which is recorded here rather than worked around -- a
hand-rolled exact interval would have been this author's arithmetic checking this author's
arithmetic.

Criteria, fixed before running:

1. **The ratio** to within 1e-9. It is one division and there is nothing to approximate.
2. **Both interval bounds** to within 1e-6 of statsmodels at `wald-log`.
3. **The z quantile**, 1.9600, against `scipy.stats.norm.ppf`, because Fieldwork hard-codes it.
4. **Dimensionlessness**: the rate's multiplier must not reach the ratio. Recomputed from raw
   counts here, so a multiplier leaking in would show as disagreement.
5. **The score interval** is reported beside the declared one, never asserted equal.

What this cannot establish: **that the comparison is fair.** The two companies' customers were
not randomised and no interval speaks to confounding; Snow's own argument rests on the
intermixing of supplies within the same streets, which is a fact about the setting. Nor that the
log-normal interval is adequate at small counts -- 18 events in the Lambeth-only group is where
`exact-cond` is reported for exactly that reason.

Design record: fieldwork/docs/experiments/139-a-rate-ratio-with-an-interval.md
"""
import json
import math
import pathlib
import platform
import sys
from datetime import datetime, timezone

import scipy
import statsmodels
from scipy.stats import norm
from statsmodels.stats.rates import confint_poisson_2indep

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "rate-ratio-snow-001.json"
RESULT = HERE.parent / "results" / "check-27-rate-ratio.json"

RATIO_TOL = 1e-9
BOUND_TOL = 1e-6


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    text = fixture_path.read_text(encoding="utf-8")
    fixture = json.loads(text)
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    comparisons = []
    divergences = []
    for c in fixture["output"]["comparisons"]:
        a, na = c["compared"]["events"], c["compared"]["unitsAtRisk"]
        b, nb = c["reference"]["events"], c["reference"]["unitsAtRisk"]

        # Recomputed from the raw counts, never from Fieldwork's rates: a multiplier that leaked
        # into the ratio would show up here as disagreement rather than being reproduced.
        ratio = (a / na) / (b / nb)
        f = float  # statsmodels returns numpy scalars; record plain numbers.
        lo, hi = (f(v) for v in confint_poisson_2indep(a, na, b, nb, method="wald-log", alpha=0.05))
        score_lo, score_hi = (f(v) for v in confint_poisson_2indep(a, na, b, nb, method="score", alpha=0.05))

        agrees = bool(
            abs(ratio - c["ratio"]) <= RATIO_TOL
            and abs(lo - c["lower"]) <= BOUND_TOL
            and abs(hi - c["upper"]) <= BOUND_TOL
        )
        if not agrees:
            divergences.append(
                {
                    "note": c["note"],
                    "fieldwork": [c["ratio"], c["lower"], c["upper"]],
                    "statsmodels": [ratio, lo, hi],
                }
            )
        comparisons.append(
            {
                "note": c["note"],
                "denominatorUnit": c["denominatorUnit"],
                "counts": {"comparedEvents": a, "comparedUnits": na,
                           "referenceEvents": b, "referenceUnits": nb},
                "fieldwork": {"ratio": c["ratio"], "lower": c["lower"], "upper": c["upper"]},
                "statsmodels": {"ratio": ratio, "lower": lo, "upper": hi},
                "scoreMethod": {"lower": score_lo, "upper": score_hi},
                # What choosing wald-log costs against a score interval, per bound.
                "methodDifference": {
                    "lower": abs(lo - score_lo) / score_lo,
                    "upper": abs(hi - score_hi) / score_hi,
                },
                "agrees": agrees,
            }
        )

    z = float(norm.ppf(0.975))
    z_agrees = bool(abs(z - 1.9600) < 5e-5)

    result = {
        "check": "27-rate-ratio",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "statsmodels": statsmodels.__version__,
            "scipy": scipy.__version__,
        },
        "fixture": {"id": fixture["id"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "criterion": {
            "ratio": f"within {RATIO_TOL} of statsmodels",
            "bounds": f"within {BOUND_TOL} of confint_poisson_2indep(method='wald-log')",
            "z": "1.9600 within 5e-5 of scipy.stats.norm.ppf(0.975)",
        },
        "zQuantile": {"fieldwork": 1.9600, "scipy": z, "agrees": z_agrees},
        "comparisons": comparisons,
        "divergences": divergences,
        "notEstablished": [
            "That the comparison is fair: no interval speaks to confounding, and these customers "
            "were not randomised.",
            "That the log-normal interval is adequate at small counts. The Lambeth-only group has "
            "18 events; a score interval is reported beside it rather than asserted equal. An "
            "exact conditional interval would be the better comparison and statsmodels documents "
            "that method as not yet implemented.",
            "What the right denominator is. Houses and people give different ratios over the same "
            "outbreak, and choosing between them is the practitioner's.",
        ],
        "agrees": bool(not divergences and z_agrees),
    }
    return result


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    comparisons = result["comparisons"]
    z, z_agrees = result["zQuantile"]["scipy"], result["zQuantile"]["agrees"]
    for c in comparisons:
        print(f"{'OK ' if c['agrees'] else 'DIFF'} {c['fieldwork']['ratio']:.4f} "
              f"[{c['fieldwork']['lower']:.4f}, {c['fieldwork']['upper']:.4f}]  "
              f"score [{c['scoreMethod']['lower']:.4f}, {c['scoreMethod']['upper']:.4f}]  "
              f"{c['note']}")
    print(f"z: fieldwork 1.9600, scipy {z:.6f}, agrees {z_agrees}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
