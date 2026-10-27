"""Check 30: Fieldwork Two-by-two table against statsmodels.

Risk in each group, the risk ratio, the odds ratio and the risk difference, over John Snow's
1855 figures -- on PEOPLE, from Table VIII grouped by Table XII's declared water supply, and on
HOUSES, from Table IX.

**Why this widget and why now.** It was built four days before the South London example is shown
to FETP-trained epidemiologists, and the layout it is patterned after is one they were trained to
read. Every number in it rested on Fieldwork's own tests.

**Genuinely independent.** `statsmodels.stats.contingency_tables.Table2x2` is a separate
implementation by separate authors of the same estimators, with the same interval forms: Katz log
for the risk ratio (`riskratio_confint`) and Wald log for the odds ratio (`oddsratio_confint`).
`Table2x2` DOES NOT CARRY A RISK DIFFERENCE -- checked against the installed 0.15.0 rather than
assumed -- so that one is compared against
`statsmodels.stats.proportion.confint_proportions_2indep(compare='diff', method='wald')`, which is
the unpooled Wald, with `agresti-caffo` carried beside it as a third opinion in the role `score`
plays in check 27: a different interval for the same quantity, so what the declared choice costs
is visible rather than hidden.

statsmodels orders its table [[a, b], [c, d]] with exposure down the rows and the case column
first, which is the orientation Fieldwork's request names explicitly -- a transposed table would
produce a confident disagreement about nothing, so the orientation is asserted here rather than
assumed.

**What this check found, on its first run, before the widget shipped.** Fieldwork's own
documentation explained the 8.40-against-5.35 gap in the South London project as rate-versus-risk:
a RATE ratio of 8.40 per house beside a 2x2 where the RISK ratio on people is 5.35. Computing a
risk ratio over the same houses refutes it. It is 8.401853429780243 -- the rate ratio's value BIT
FOR BIT, because deaths per house IS a risk when a house can hold at most one death, so the two
are the same division. Only the intervals differ, and only in the second decimal: 6.8410 to
10.3189 from the Poisson form against 6.8450 to 10.3128 from Katz.

So the 57% gap is the DENOMINATOR, a house against a person, and not the estimand. Both tables are
carried in the fixture for exactly this reason: the comparison between them is the finding, and it
makes the hazard worse rather than milder. A reader who takes 8.40 for the risk ratio beside the
houses table is RIGHT, and is thereby taught that the substitution is safe -- which holds only
while the outcome is rare.

Criteria, fixed before running:

1. **Every estimate** to within 1e-9 of statsmodels. Each is a ratio or difference of two
   quotients and there is nothing to approximate.
2. **Every interval bound** to within 1e-9 at the matching method. Tighter than check 27's 1e-6,
   because the normal quantile is now shared from `src/epi-estimate.ts` rather than typed per
   file: check 27 found 1.9600 standing in for 1.959963984540054, and 1e-9 is what detects that
   class of defect rather than tolerating it.
3. **The orientation**, asserted by recomputing the risks from the fixture's own cells and
   comparing them with the risks Fieldwork reported. A transposed table agrees on the odds ratio
   and disagrees on everything else, so this separates the two failures.
4. **The denominator finding** is recorded as a comparison between the two tables and never
   asserted equal: 8.4019 against 5.3511 is the point.
5. **The Epi Info label** on every estimate must be present AND must name its source. Changed
   2026-10-26: the labels were previously required to be null, because nobody had read Epi Info's
   displayed labels. They have since been transcribed from the classic TABLES estimate table in
   `epi-info-ai/wasm/demo/app.ts` -- `Risk Ratio (RR)`, `Odds Ratio (cross product)`,
   `Risk Difference (RD%)`. That is a sibling project's rendering of Epi Info, so the criterion is
   now that `epiInfoLabelSource` says `epi-info-ai-results-panel` and NOT `epi-info`: this check
   fails if a label ever claims to have been verified against Epi Info itself, which nobody has
   done. A bare label with no source fails too. The purpose is unchanged -- a field that can be
   filled unverifiably is worse than no field -- but what it polices is now the provenance rather
   than the absence.

What this cannot establish: **agreement with Epi Info.** statsmodels is not Epi Info, and this
project makes no parity claim -- see fieldwork/docs/directions.json,
`recognisable-not-identical-an-epi-kernel-of-our-own`. Nor **that the comparison is fair**: the
both-companies stratum holding 16 of 32 sub-districts is excluded by name and not controlled for,
which is Snow's own confounding and the reason he went to the house level. Nor **that the normal
approximations are adequate** -- the Lambeth-only group has 18 deaths, and an exact interval would
be the better comparison there.

Design record: fieldwork/docs/experiments/142-an-epi-kernel-exercised.md
"""
import hashlib
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

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "two-by-two-snow-001.json"
RESULT = HERE.parent / "results" / "check-30-two-by-two.json"

TOL = 1e-9
ALPHA = 0.05

# Fieldwork's name for each estimate, and the method name it must declare. The two ratios come
# from Table2x2; the difference does not exist there and comes from confint_proportions_2indep.
METHODS = {
    "risk ratio": ("Katz log", "riskratio", "riskratio_confint"),
    "odds ratio": ("Wald log", "oddsratio", "oddsratio_confint"),
    "risk difference": ("Wald unpooled", None, None),
}


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    text = fixture_path.read_text(encoding="utf-8")
    fixture = json.loads(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    tables, divergences, label_leaks = [], [], []
    for t in fixture["output"]["tables"]:
        c = t["cells"]
        a, b = c["exposedCases"], c["exposedNonCases"]
        d, e = c["unexposedCases"], c["unexposedNonCases"]
        # Exposure down the rows, the case column first: the orientation the request names.
        sm = Table2x2([[a, b], [d, e]])

        # Recomputed from the cells, never read from Fieldwork's own risks, so a transposed
        # table shows as disagreement here rather than being reproduced.
        risk_exposed, risk_unexposed = a / (a + b), d / (d + e)
        orientation = {
            "riskExposed": {"fieldwork": t["riskExposed"], "recomputed": risk_exposed},
            "riskUnexposed": {"fieldwork": t["riskUnexposed"], "recomputed": risk_unexposed},
            "agrees": bool(abs(t["riskExposed"] - risk_exposed) <= TOL
                           and abs(t["riskUnexposed"] - risk_unexposed) <= TOL),
        }
        if not orientation["agrees"]:
            divergences.append({"note": t["note"], "what": "orientation",
                                "fieldwork": [t["riskExposed"], t["riskUnexposed"]],
                                "recomputed": [risk_exposed, risk_unexposed]})

        estimates = []
        for estimate in t["estimates"]:
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

            # A label must be present and must say where it came from, and it must not claim Epi
            # Info itself. A "leak" is now an unsourced or over-claimed label rather than any
            # label at all -- see criterion 5.
            source = estimate.get("epiInfoLabelSource")
            if not estimate["epiInfoLabel"]:
                label_leaks.append({"note": t["note"], "estimate": name,
                                    "problem": "no label"})
            elif source != "epi-info-ai-results-panel":
                label_leaks.append({"note": t["note"], "estimate": name,
                                    "label": estimate["epiInfoLabel"],
                                    "problem": f"source is {source!r}, and only the Epi Info AI "
                                               "results panel has been read"})

            agrees = bool(
                estimate["method"] == method
                and estimate["value"] is not None
                and abs(estimate["value"] - value) <= TOL
                and abs(estimate["lower"] - lo) <= TOL
                and abs(estimate["upper"] - hi) <= TOL
            )
            if not agrees:
                divergences.append({
                    "note": t["note"], "what": name,
                    "fieldwork": [estimate["value"], estimate["lower"], estimate["upper"],
                                  estimate["method"]],
                    "statsmodels": [value, lo, hi, method]})
            estimates.append({
                "name": name,
                "method": {"fieldwork": estimate["method"], "expected": method},
                "fieldwork": {"value": estimate["value"], "lower": estimate["lower"],
                              "upper": estimate["upper"]},
                "statsmodels": {"value": value, "lower": lo, "upper": hi},
                "epiInfoLabel": estimate["epiInfoLabel"],
                "epiInfoLabelSource": source,
                # Never asserted equal. Reported so the declared choice has a visible cost.
                "thirdOpinion": third,
                "agrees": agrees,
            })

        tables.append({
            "note": t["note"], "cells": c,
            "subjects": {"exposed": t["exposedTotal"], "unexposed": t["unexposedTotal"]},
            "strataLeftOut": t["strataLeftOut"],
            "orientation": orientation,
            "estimates": estimates,
        })

    # THE FINDING, recorded as a comparison rather than a criterion. Carried because the
    # fixture's two tables exist to be compared: the risk ratios differ by the subject counted,
    # not by the estimand, and this is the number that says so.
    risk_ratios = {t["note"]: next(e["fieldwork"]["value"] for e in t["estimates"]
                                   if e["name"] == "risk ratio") for t in tables}
    denominator_finding = {
        "riskRatios": risk_ratios,
        "rateRatioOnHouses": 8.401853429780243,
        "note": "The houses risk ratio and the rate ratio over the same houses are the SAME "
                "NUMBER, bit for bit: deaths per house is a risk when a house can hold at most "
                "one death, so the two are the same division. Only the intervals differ, and "
                "only in the second decimal. What moves the number to the people figure is the "
                "subject counted, which no part of the layout names.",
    }

    z = float(norm.ppf(1 - ALPHA / 2))
    result = {
        "check": "30-two-by-two",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} "
                       f"{platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "statsmodels": statsmodels.__version__,
            "scipy": scipy.__version__,
        },
        "fixture": {"id": fixture["id"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "criterion": {
            "estimates": f"within {TOL} of statsmodels Table2x2",
            "bounds": f"within {TOL} of the matching Table2x2 confint at alpha={ALPHA}",
            "orientation": "risks recomputed from the fixture's cells match the reported risks",
            "epiInfoLabel": "present on every estimate, with epiInfoLabelSource naming the "
                            "Epi Info AI results panel and never Epi Info itself, which "
                            "nobody has read",
        },
        "zQuantile": {"shared": 1.959963984540054, "scipy": z,
                      "agrees": bool(abs(z - 1.959963984540054) <= 1e-12)},
        "tables": tables,
        "denominatorFinding": denominator_finding,
        "divergences": divergences,
        "epiInfoLabelLeaks": label_leaks,
        "notEstablished": [
            "Agreement with Epi Info. statsmodels is not Epi Info and this project makes no "
            "parity claim. Nor do the labels establish it: they were read from Epi Info AI's "
            "results panel, a sibling project synthesized from Epi Info, which makes them a "
            "deduction about what Epi Info prints and not a reading of it.",
            "That the comparison is fair. The both-companies stratum, 16 of 32 sub-districts, is "
            "excluded by name and not controlled for -- Snow's own confounding, and the reason he "
            "went to the house level.",
            "That the normal approximations are adequate. The Lambeth-only group has 18 deaths; an "
            "exact interval would be the better comparison there.",
            "Which denominator is right. Houses and people give 8.40 and 5.35 over the same "
            "outbreak, and choosing between them is the practitioner's.",
        ],
        "agrees": bool(not divergences and not label_leaks),
    }
    return result


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for t in result["tables"]:
        print(f"\n{t['note']}")
        print(f"  orientation: {'OK' if t['orientation']['agrees'] else 'DIFF'}")
        for e in t["estimates"]:
            f = e["fieldwork"]
            print(f"  {'OK ' if e['agrees'] else 'DIFF'} {e['name']:16s} "
                  f"{f['value']:.6f} [{f['lower']:.6f}, {f['upper']:.6f}]  "
                  f"{e['method']['fieldwork']}")
    rr = result["denominatorFinding"]["riskRatios"]
    print("\nrisk ratios by subject counted:")
    for note, value in rr.items():
        print(f"  {value:.4f}  {note}")
    print(f"rate ratio on the same houses: "
          f"{result['denominatorFinding']['rateRatioOnHouses']:.4f}")
    print("\nAGREES" if result["agrees"] else "\nDIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
