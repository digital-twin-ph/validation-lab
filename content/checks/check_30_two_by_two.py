"""Check 30: Fieldwork Two-by-two table against statsmodels.

Risk in each group, the risk ratio, the odds ratio and the risk difference, over John Snow's 1855 figures on PEOPLE:
Table VIII grouped by Table XII's declared water supply, as the South London example's people workflow derives them.

**Genuinely independent.** The four cells are built here by summing the rows of the table the step reads, rather than
taken from Fieldwork. `statsmodels.stats.contingency_tables.Table2x2` is a separate
implementation by separate authors of the same estimators, with the same interval forms: Katz log for the risk ratio
(`riskratio_confint`) and Wald log for the odds ratio (`oddsratio_confint`). `Table2x2` carries no risk difference, so
that one is compared against `confint_proportions_2indep(compare='diff', method='wald')`, the unpooled Wald, with
`agresti-caffo` beside it as a third opinion: a different interval for the same quantity, so what the declared choice
costs is visible.

statsmodels orders its table [[a, b], [c, d]] with exposure down the rows and the case column first, which is the
orientation Fieldwork's request names. A transposed table would agree on the odds ratio and disagree on everything
else, so the orientation is asserted, not assumed.

Criteria, fixed before running:

1. **The cells**: built here from the table's rows for the exposure and outcome values the step declares, equal to
   Fieldwork's exactly, and the exposure values left out named alike.
2. **Every estimate** within 1e-9 of statsmodels. Each is a ratio or difference of two quotients.
3. **Every interval bound** within 1e-9 at the matching method. 1e-9 is what detects a normal quantile typed as
   1.9600 for 1.959963984540054, which check 27 found once.
4. **The orientation**: the risks recomputed from the cells equal the risks Fieldwork reported.
5. **Each label says where it was read.** Every estimate carries a conventional label and its source. The source
   `results-panel` is a deduction from another program's published results panel, which is what was read.
   `original-program`, a claim that the label was read from that program itself, fails here, because nobody has done
   that. A label with no source fails too. A field that can be filled unverifiably is worse than no field.

What this cannot establish: that the labels are that program's own. That the comparison is fair: the both-companies
stratum is left out by name and not controlled for, which is Snow's own confounding and the reason he went to the
house level. That the normal approximations are adequate: the Lambeth-only group has 18 deaths, and an exact interval
would be the better comparison there.

**History.** First run 2026-10-26 on two-by-two-snow-001, made at Fieldwork 0.12.0 by a chain that is gone, with a
second table on houses. That table showed the houses risk ratio equal, bit for bit, to the rate ratio over the same
houses (8.401853429780243), so the gap to 5.35 on people is the denominator, not the estimand. The houses comparison
is the rate layout now, and check 27 carries it. **Rewritten 2026-11-26** on two-by-two-snow-002, which Fieldwork makes
from the people workflow itself, with the label fields under their current names.

Design record: fieldwork/docs/experiments/142-an-epi-kernel-exercised.md
"""
import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

import scipy
import statsmodels
from scipy.stats import norm
from statsmodels.stats.contingency_tables import Table2x2
from statsmodels.stats.proportion import confint_proportions_2indep

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "two-by-two-snow-002.json"
RESULT = HERE.parent / "results" / "check-30-two-by-two.json"

TOL = 1e-9
ALPHA = 0.05
READ_FROM = "results-panel"

# Fieldwork's name for each estimate, and the method name it must declare.
METHODS = {
    "risk ratio": ("Katz log", "riskratio", "riskratio_confint"),
    "odds ratio": ("Wald log", "oddsratio", "oddsratio_confint"),
    "risk difference": ("Wald unpooled", None, None),
}


def cells_from(table: dict, declared: dict) -> tuple[dict, list[str]]:
    """The four cells, summed from the rows for the declared exposure and outcome values."""
    exposure, outcome = declared["exposureColumn"], declared["outcomeColumn"]
    want = {(declared["exposed"], declared["caseValue"]): "exposedCases",
            (declared["exposed"], declared["nonCaseValue"]): "exposedNonCases",
            (declared["unexposed"], declared["caseValue"]): "unexposedCases",
            (declared["unexposed"], declared["nonCaseValue"]): "unexposedNonCases"}
    cells = {name: 0 for name in want.values()}
    left_out = set()
    for row in table["rows"]:
        group, measure = row["key"][exposure], row["key"][outcome]
        if (group, measure) in want:
            cells[want[(group, measure)]] += row["value"]
        elif group not in (declared["exposed"], declared["unexposed"]):
            left_out.add(group)
    return cells, sorted(left_out)


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    fixture, digest = load_fixture(fixture_path)
    declared, out = fixture["declaredParameters"], fixture["output"]
    divergences, label_problems = [], []

    cells, left_out = cells_from(fixture["input"]["table"], declared)
    cells_agree = cells == out["cells"] and left_out == sorted(out["strataLeftOut"])
    if not cells_agree:
        divergences.append({"what": "cells", "fieldwork": [out["cells"], out["strataLeftOut"]],
                            "recomputed": [cells, left_out]})

    a, b = cells["exposedCases"], cells["exposedNonCases"]
    d, e = cells["unexposedCases"], cells["unexposedNonCases"]
    sm = Table2x2([[a, b], [d, e]])
    risk_exposed, risk_unexposed = a / (a + b), d / (d + e)
    orientation = {
        "riskExposed": {"fieldwork": out["riskExposed"], "recomputed": risk_exposed},
        "riskUnexposed": {"fieldwork": out["riskUnexposed"], "recomputed": risk_unexposed},
        "agrees": bool(abs(out["riskExposed"] - risk_exposed) <= TOL
                       and abs(out["riskUnexposed"] - risk_unexposed) <= TOL),
    }
    if not orientation["agrees"]:
        divergences.append({"what": "orientation", "fieldwork": [out["riskExposed"], out["riskUnexposed"]],
                            "recomputed": [risk_exposed, risk_unexposed]})

    estimates = []
    for estimate in out["estimates"]:
        name = estimate["name"]
        method, point_attr, confint_attr = METHODS[name]
        third = None
        if point_attr is None:
            value = risk_exposed - risk_unexposed
            lo, hi = (float(v) for v in confint_proportions_2indep(
                a, a + b, d, d + e, compare="diff", method="wald", alpha=ALPHA))
            caffo_lo, caffo_hi = (float(v) for v in confint_proportions_2indep(
                a, a + b, d, d + e, compare="diff", method="agresti-caffo", alpha=ALPHA))
            third = {"method": "agresti-caffo", "lower": caffo_lo, "upper": caffo_hi}
        else:
            value = float(getattr(sm, point_attr))
            lo, hi = (float(v) for v in getattr(sm, confint_attr)(alpha=ALPHA))

        label, source = estimate.get("conventionalLabel"), estimate.get("conventionalLabelSource")
        if not label:
            label_problems.append({"estimate": name, "problem": "no label"})
        elif source != READ_FROM:
            label_problems.append({"estimate": name, "label": label,
                                   "problem": f"source is {source!r}; only the published results panel has been read"})

        agrees = bool(estimate["method"] == method and estimate["value"] is not None
                      and abs(estimate["value"] - value) <= TOL
                      and abs(estimate["lower"] - lo) <= TOL and abs(estimate["upper"] - hi) <= TOL)
        if not agrees:
            divergences.append({"what": name,
                                "fieldwork": [estimate["value"], estimate["lower"], estimate["upper"], estimate["method"]],
                                "statsmodels": [value, lo, hi, method]})
        estimates.append({
            "name": name,
            "method": {"fieldwork": estimate["method"], "expected": method},
            "fieldwork": {"value": estimate["value"], "lower": estimate["lower"], "upper": estimate["upper"]},
            "statsmodels": {"value": value, "lower": lo, "upper": hi},
            "label": label, "labelSource": source,
            # Never asserted equal. Reported so the declared choice has a visible cost.
            "thirdOpinion": third,
            "agrees": agrees,
        })

    z = float(norm.ppf(1 - ALPHA / 2))
    return {
        "check": "30-two-by-two",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} "
                       f"{platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "statsmodels": statsmodels.__version__,
            "scipy": scipy.__version__,
        },
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "criterion": {
            "cells": "built here from the table's rows, equal exactly, and the same exposure values left out",
            "estimates": f"within {TOL} of statsmodels Table2x2",
            "bounds": f"within {TOL} of the matching statsmodels interval at alpha={ALPHA}",
            "orientation": "risks recomputed from the cells match the reported risks",
            "labels": f"present on every estimate, with its source {READ_FROM!r} and never 'original-program'",
        },
        "zQuantile": {"shared": 1.959963984540054, "scipy": z,
                      "agrees": bool(abs(z - 1.959963984540054) <= 1e-12)},
        "cells": {"fieldwork": out["cells"], "recomputed": cells, "leftOut": left_out, "agrees": cells_agree},
        "subjects": {"exposed": out["exposedTotal"], "unexposed": out["unexposedTotal"]},
        "orientation": orientation,
        "estimates": estimates,
        "divergences": divergences,
        "labelProblems": label_problems,
        "notEstablished": [
            "That the labels are that program's own. They were read from another program's published results "
            "panel, which makes them a deduction about what that program prints, not a reading of it.",
            "That the comparison is fair. The both-companies stratum is left out by name and not controlled for: "
            "Snow's own confounding, and the reason he went to the house level.",
            "That the normal approximations are adequate. The Lambeth-only group has 18 deaths; an exact interval "
            "would be the better comparison there.",
        ],
        "agrees": bool(not divergences and not label_problems),
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("AGREES" if report["agrees"] else "DIVERGES")
    for estimate in report["estimates"]:
        f, s = estimate["fieldwork"], estimate["statsmodels"]
        print(f"  {estimate['name']:16} {f['value']:.6f} ({f['lower']:.6f} to {f['upper']:.6f}) "
              f"statsmodels {s['value']:.6f} ({s['lower']:.6f} to {s['upper']:.6f})  {estimate['agrees']}")
    print(f"Wrote {RESULT.relative_to(HERE.parent.parent)}")
