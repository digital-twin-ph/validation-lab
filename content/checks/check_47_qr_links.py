"""Check 47: the QR codes Fieldwork prints in a worked example's write-up, read back by a decoder by other authors.

Fieldwork experiment 203: a worked example's write-up carries two QR codes, Fieldwork with the example opened and the
example's own files. The fixture is every address Fieldwork would print, for the nine catalog examples and the three
built-in ones, with the code Fieldwork's encoder draws for each (qrcode-generator 2.0.4, error correction M, byte mode,
the smallest version that holds the address).

**Independent.** OpenCV's QR detector (Apache 2.0) reads each code, drawn here from the fixture's modules with the
standard's four-module quiet zone. segno (BSD), a second encoder, draws its own code for the same address at the same
version and error correction. Nothing of Fieldwork's code is read.

Criteria, fixed before running:

1. **Every code reads back to its address**, exactly, by OpenCV.
2. **segno agrees on the size**: the same version, so the same number of modules, for every address.
3. **segno's own code reads back too**, so the decoder is shown able to read a code it did not make by Fieldwork's
   encoder; a failure on Fieldwork's codes alone would then be Fieldwork's.

Reported, not required: whether segno draws the identical pattern. Both choose a mask by the standard's penalty rule,
and the same pattern says the encoders agree to the module; a different one is still a valid code if criterion 1
holds.

What this cannot establish: that a phone camera reads a printed code at a given size and light; that an address
answers; that the pinned commit is the one the write-up was made from. Those are the export's checks, not the code's.

CPython only: OpenCV is not in the browser kernel.

Design record: fieldwork/docs/experiments/203-qr-codes-from-a-product-to-its-digital-form.md
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

import cv2
import numpy as np
import segno

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "qr-links-001.json"
RESULT = HERE.parent / "results" / "check-47-qr-links.json"
SCALE = 8


def image(rows: list[list[bool]]) -> np.ndarray:
    """The modules as a black-on-white image, with a four-module quiet zone, SCALE pixels a module."""
    n = len(rows)
    grid = np.ones((n + 8, n + 8), dtype=np.uint8) * 255
    for r, row in enumerate(rows):
        for c, dark in enumerate(row):
            if dark:
                grid[r + 4, c + 4] = 0
    return np.kron(grid, np.ones((SCALE, SCALE), dtype=np.uint8))


def decode(img: np.ndarray) -> str:
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return text


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    rows_out, differs = [], []
    for code in fixture["output"]["codes"]:
        theirs = [[ch == "1" for ch in row] for row in code["rows"]]
        n = len(theirs)
        version = (n - 17) // 4
        read = decode(image(theirs))
        other = segno.make(code["text"], error="m", mode="byte", version=version, boost_error=False)
        mine = [[bool(v) for v in row] for row in other.matrix]
        mine_read = decode(image(mine))
        same_size = len(mine) == n
        same_pattern = mine == theirs
        row = {"text": code["text"], "version": version, "readBack": read == code["text"],
               "segnoSameSize": same_size, "segnoReadBack": mine_read == code["text"], "segnoSamePattern": same_pattern}
        rows_out.append(row)
        problems = [k for k in ("readBack", "segnoSameSize", "segnoReadBack") if not row[k]]
        if problems:
            differs.append({"text": code["text"], "problems": problems, "read": read})
    return {
        "check": "47-qr-links",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": not differs,
        "criteria": "Every code reads back to its address by OpenCV; segno makes a code of the same version for it, and "
                    "segno's own code reads back too",
        "addresses": len(rows_out),
        "samePatternAsSegno": sum(r["segnoSamePattern"] for r in rows_out),
        "codes": rows_out,
        "differs": differs,
        "notEstablished": [
            "That a phone camera reads a printed code at a given size and light.",
            "That an address answers, or that the pinned commit is the one the write-up was made from: the export's checks.",
            "Anything in the browser kernel: OpenCV is not there, so this ran in CPython only.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "opencv": cv2.__version__, "segno": segno.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
