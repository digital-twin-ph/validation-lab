"""Check 52: the QR codes Fieldwork prints with its mark in the middle, read back by a decoder by other authors.

Fieldwork, 2026-11-14 (the practitioner: "Can we add the FW logo to the QR code?"): a worked example's codes are drawn
at error correction H with the middle modules cleared for Fieldwork's mark. The fixture is every address Fieldwork would
print, with the modules as drawn and where the mark sits.

**Independent.** OpenCV (Apache 2.0) reads each code, drawn here from the fixture's modules with the four-module quiet
zone, by its two detectors, the classic one and the ArUco-based one, at four sizes. Each code is read twice: with the
mark's patch light, as the fixture draws it, and with the patch dark, as a camera may read a dark green mark. segno
(BSD) draws its own code for each address at H and the same version, with no mark, as a control on the decoder: a code
segno makes that OpenCV cannot read is the decoder's limit, not the mark's.

Criteria, fixed before running:

1. **Every marked code reads back to its address**, exactly, by at least one of OpenCV's detectors, with the patch
   light and with it dark.
2. **Where a detector misses a marked code, it misses segno's unmarked code too**, so no miss is the mark's.

What this cannot establish: that a phone camera reads a printed code at a given size and light, or that every reader
app tolerates the mark as OpenCV does.

CPython only: OpenCV is not in the browser kernel.
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

try:
    import cv2
except ImportError as missing:  # CPython only
    raise ImportError("The browser kernel does not have OpenCV, the QR decoder this check reads every code with; run this check in CPython.") from missing
import numpy as np
import segno

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "qr-mark-001.json"
RESULT = HERE.parent / "results" / "check-52-qr-mark.json"
SCALES = (5, 6, 8, 10)
DETECTORS = {"classic": cv2.QRCodeDetector, "aruco": cv2.QRCodeDetectorAruco}


def image(rows, scale, dark=None):
    n = len(rows)
    grid = np.full((n, n), 255, dtype=np.uint8)
    for r, row in enumerate(rows):
        for c, on in enumerate(row):
            if on:
                grid[r, c] = 0
    if dark:
        a, b = dark["at"], dark["box"]
        grid[a:a + b, a:a + b] = 40
    grid = np.pad(grid, 4, constant_values=255)
    return np.kron(grid, np.ones((scale, scale), dtype=np.uint8))


def reads(name, rows, text, dark=None):
    det = DETECTORS[name]()
    return any(det.detectAndDecode(image(rows, s, dark))[0] == text for s in SCALES)


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    out, differs = [], []
    for code in fixture["output"]["codes"]:
        rows = [[ch == "1" for ch in r] for r in code["rows"]]
        version = (len(rows) - 17) // 4
        control = [[bool(v) for v in r] for r in segno.make(code["text"], error="h", mode="byte", version=version,
                                                            boost_error=False).matrix]
        row = {"text": code["text"], "version": version}
        for name in DETECTORS:
            row[name] = {"light": reads(name, rows, code["text"]), "dark": reads(name, rows, code["text"], code["mark"]),
                         "segno": reads(name, control, code["text"])}
        out.append(row)
        if not any(row[n]["light"] for n in DETECTORS) or not any(row[n]["dark"] for n in DETECTORS):
            differs.append({"text": code["text"], "problem": "no detector reads it"})
        for n in DETECTORS:
            if (not row[n]["light"] or not row[n]["dark"]) and row[n]["segno"]:
                differs.append({"text": code["text"], "problem": f"{n} reads segno's unmarked code and not the marked one"})
    count = lambda n, k: sum(r[n][k] for r in out)
    return {
        "check": "52-qr-mark",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": not differs,
        "criteria": "Every marked code reads back by at least one OpenCV detector, patch light and dark; no detector reads "
                    "segno's unmarked code of the same version and misses the marked one",
        "addresses": len(out),
        "read": {n: {k: count(n, k) for k in ("light", "dark", "segno")} for n in DETECTORS},
        "codes": out,
        "differs": differs,
        "notEstablished": [
            "That a phone camera reads a printed code with the mark at a given size and light.",
            "That every reader app tolerates the mark as OpenCV does.",
            "Anything in the browser kernel: OpenCV is not there, so this ran in CPython only.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "opencv": cv2.__version__, "segno": segno.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"], report["read"])
    for d in report["differs"]:
        print(" ", d)
