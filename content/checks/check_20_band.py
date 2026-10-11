"""Check 20: Fieldwork Travel time band against an independent threshold.

Selecting the junctions within a band is an exact threshold test, so the arithmetic is not the
interesting part. What this check is really for is the **design claim**: the widget restates
neither the speed nor the direction, reading both from the junctions it is given, so a band
cannot disagree with the traversal that produced it.

That claim is testable. The reference recomputes the band budget from the speed carried **on
the junctions** -- not from any parameter of its own -- and selects on that.

Five comparisons, criteria fixed before running:

1. **The band budget**, as minutes x the speed the junctions carry.
2. **Which junctions are in the band**, exactly, as a set.
3. **Each junction's remaining budget**, recomputed against the band rather than carried over
   from the traversal. This is the part most likely to be got wrong: a junction 300 m along a
   375 m band has 75 m left of the band, not the 825 m it had left of a 1,125 m traversal.
4. **The counts** offered and selected.
5. **That the band is nested, not a ring**: no junction is excluded for being too close.

Tolerances are half of the last digit the widget reports, which is two decimals on metres.

What this cannot establish: that 75 m per minute is the right walking speed, or that a band
boundary falling between junctions is where the five-minute line really is. The corridor widget
addresses the second; the first is an assumption two co-authors arrived at from photographs of
1854 Soho, and it travels on the junctions so that nothing downstream can contradict it.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

TOLERANCE_M = 5e-3   # Half of the two decimals the widget reports metres to.
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    minutes = declared["bandMinutes"]

    junctions = fixture["input"]["junctions"]
    speeds = {j["assumedSpeedMetresPerMinute"] for j in junctions}
    if len(speeds) != 1:
        raise SystemExit(f"The junctions carry {len(speeds)} different speeds; a band needs one.")
    speed = speeds.pop()
    directions = {j["travelDirection"] for j in junctions}

    # The budget comes from the speed on the junctions, which is the claim being checked.
    band_budget = minutes * speed
    reference = {}
    for junction in junctions:
        if junction["travelMetres"] <= band_budget + TOLERANCE_M:
            reference[junction["networkNodeId"]] = band_budget - junction["travelMetres"]

    reported = {j["networkNodeId"]: j for j in fixture["output"]["inBand"]}
    missing = sorted(set(reference) - set(reported))
    extra = sorted(set(reported) - set(reference))

    worst_remaining_error = 0.0
    band_minutes_stamped = True
    for identifier in sorted(set(reference) & set(reported)):
        row = reported[identifier]
        worst_remaining_error = max(worst_remaining_error, abs(row["remainingM"] - reference[identifier]))
        if row.get("bandMinutes") != minutes:
            band_minutes_stamped = False

    budget_error = abs(fixture["output"]["bandBudgetMetres"] - band_budget)
    counts_agree = (fixture["output"]["junctionsOffered"] == len(junctions)
                    and fixture["output"]["junctionsInBand"] == len(reference))
    # Nested, not a ring: everything inside the band is kept, including the origin itself.
    nearest_kept = min((j["travelMetres"] for j in junctions
                        if j["networkNodeId"] in reported), default=None)
    nearest_offered = min(j["travelMetres"] for j in junctions)
    nested = nearest_kept == nearest_offered

    agrees = bool(not missing and not extra and counts_agree and nested and band_minutes_stamped
                  and budget_error <= TOLERANCE_M and worst_remaining_error <= TOLERANCE_M)

    return {
        "check": "20-band",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "note": "No geometry library is needed: a band is a threshold on distances the junctions carry.",
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredRule": declared["rule"],
        },
        "criterion": (
            f"the band budget within {TOLERANCE_M:g} m of minutes x the speed carried on the junctions, the same "
            f"junctions selected, every remaining budget recomputed against the band to within {TOLERANCE_M:g} m, "
            f"the counts exact, every kept junction stamped with the band, and the band nested rather than a ring"
        ),
        "bandMinutes": minutes,
        "speedFromTheJunctions": speed,
        "directionFromTheJunctions": sorted(directions),
        "referenceBandBudgetMetres": band_budget,
        "fieldworkBandBudgetMetres": fixture["output"]["bandBudgetMetres"],
        "traversalBudgetMetres": fixture["output"]["traversalBudgetMetres"],
        "junctionsOffered": len(junctions),
        "junctionsInBand": len(reference),
        "budgetErrorMetres": budget_error,
        "worstRemainingBudgetErrorMetres": worst_remaining_error,
        "missingFromOutput": missing,
        "notInReference": extra,
        "countsAgree": counts_agree,
        "everyKeptJunctionStampedWithTheBand": band_minutes_stamped,
        "nestedNotARing": nested,
        "notEstablished": (
            "That 75 m per minute is the right walking speed, or that a band boundary falling between junctions "
            "is where the five-minute line really is. The speed is an assumption that travels on the junctions "
            "so nothing downstream can contradict it; the corridor widget addresses the boundary."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "band-soho-001.json")
    out = ROOT / "results" / "check-20-band.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 20: agrees={result['agrees']} -> {out.relative_to(ROOT.parent)}")
    print(f"  {result['junctionsInBand']} of {result['junctionsOffered']} junctions within "
          f"{result['referenceBandBudgetMetres']:.0f} m "
          f"({result['bandMinutes']} min x {result['speedFromTheJunctions']} m/min from the junctions)")
    print(f"  worst remaining-budget error {result['worstRemainingBudgetErrorMetres']:.3e} m, "
          f"nested: {result['nestedNotARing']}")
