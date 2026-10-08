"""Check 02: Fieldwork Clip raster against rasterio.mask.

Rebuilds each clip case from the GeoTIFF, the cutline and the case options, then
compares the cropped window, the included-cell set and the retained values.
Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/41-validation-lab.md
"""
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
import rasterio.mask
import scipy
import shapely
from scipy.ndimage import binary_dilation

ROOT = Path(__file__).resolve().parent.parent


def verified(path: Path) -> bytes:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = (path.parent / (path.name + ".sha256")).read_text().split()[0]
    if digest != expected:
        raise SystemExit(f"Hash mismatch for {path.name}: {digest} != {expected}")
    return raw


def rows_to_mask(rows: list[str]) -> np.ndarray:
    return np.array([[c == "1" for c in row] for row in rows], dtype=bool)


def reference_mask(tif: Path, cutline: dict, all_touched: bool):
    """rasterio's own clip: returns the included mask and the cropped window."""
    with rasterio.open(tif) as dataset:
        data, transform = rasterio.mask.mask(
            dataset, [cutline], all_touched=all_touched, crop=True, filled=True, nodata=np.nan
        )
    band = data[0]
    return ~np.isnan(band), transform, band


def compare_case(case: dict, tif: Path, cutline: dict, grid: dict, p_cutline: dict) -> dict:
    options = case["options"]
    method, margin = options["method"], options.get("marginPixels", 0)
    all_touched = method == "all-touched"
    ref_mask, ref_transform, ref_band = reference_mask(tif, cutline, all_touched)
    fw_mask = rows_to_mask(case["includedRows"])

    modelled = None
    if margin:
        # rasterio has no margin parameter. The margin is a Euclidean distance in native
        # pixels from the cell rectangle, so its closest discrete analogue is a one-pixel
        # dilation including diagonals. This is a model of the margin, not an equivalence.
        modelled = "one-pixel binary dilation with a 3x3 square structuring element"
        ref_mask = binary_dilation(ref_mask, structure=np.ones((3, 3), dtype=bool))
        ref_transform = rasterio.Affine(
            ref_transform.a, ref_transform.b, ref_transform.c - abs(grid["resolution"][0]),
            ref_transform.d, ref_transform.e, ref_transform.f + abs(grid["resolution"][1]),
        )

    # Fieldwork and rasterio may crop to different windows, so align both masks onto a
    # common grid before comparing. Reporting "0 differing cells" merely because the
    # windows disagree would hide the thing this check exists to find.
    window = case["window"]
    res_x, res_y = grid["resolution"]
    def place(mask, origin):
        col = round((origin[0] - grid["origin"][0]) / res_x)
        row = round((origin[1] - grid["origin"][1]) / res_y)
        full = np.zeros((grid["height"], grid["width"]), dtype=bool)
        full[row:row + mask.shape[0], col:col + mask.shape[1]] = mask
        return full

    ref_full = place(ref_mask, [ref_transform.c, ref_transform.f])
    fw_full = place(fw_mask, window["origin"])
    window_agrees = (
        ref_mask.shape == (window["height"], window["width"])
        and abs(ref_transform.c - window["origin"][0]) < 1e-9
        and abs(ref_transform.f - window["origin"][1]) < 1e-9
    )
    mask_agrees = bool(np.array_equal(ref_full, fw_full))
    differing = []
    for row, column in zip(*np.nonzero(ref_full != fw_full)):
        row, column = int(row), int(column)
        west = grid["origin"][0] + column * res_x
        north = grid["origin"][1] + row * res_y
        # Is this cell's rectangle touching a cutline vertex coordinate exactly? That is
        # where a closed-rectangle touch test and a half-open one must disagree.
        ring = p_cutline["coordinates"][0] if p_cutline["type"] == "Polygon" else p_cutline["coordinates"][0][0]
        on_pixel_edge = any(
            abs((x - grid["origin"][0]) / res_x - round((x - grid["origin"][0]) / res_x)) < 1e-9
            and min(west, west + res_x) - abs(res_x) <= x <= max(west, west + res_x) + abs(res_x)
            or abs((y - grid["origin"][1]) / res_y - round((y - grid["origin"][1]) / res_y)) < 1e-9
            and min(north, north + res_y) - abs(res_y) <= y <= max(north, north + res_y) + abs(res_y)
            for x, y in ring
        )
        differing.append({
            "row": row, "column": column,
            "reference": bool(ref_full[row, column]), "fieldwork": bool(fw_full[row, column]),
            "longitude": west + 0.5 * res_x, "latitude": north + 0.5 * res_y,
            "besidePixelAlignedCutline": on_pixel_edge,
        })

    values_agree = None
    if mask_agrees and margin == 0 and window_agrees:
        reference_values = [float(v) for v in ref_band[ref_mask]]
        values_agree = reference_values == [float(v) for v in case["includedValues"]]

    return {
        "options": options,
        "marginModelledAs": modelled,
        "referenceWindow": {"origin": [ref_transform.c, ref_transform.f],
                            "width": int(ref_mask.shape[1]), "height": int(ref_mask.shape[0])},
        "fieldworkWindow": {"origin": window["origin"], "width": window["width"], "height": window["height"]},
        "windowAgrees": window_agrees,
        "referenceIncluded": int(ref_mask.sum()),
        "fieldworkIncluded": int(fw_mask.sum()),
        "maskAgrees": mask_agrees,
        "differingCells": differing[:60],
        "differingCellCount": len(differing),
        "retainedValuesAgree": values_agree,
    }


def run(fixture_path: Path) -> dict:
    raw = verified(fixture_path)
    fixture = json.loads(raw)
    p = fixture["declaredParameters"]
    tif = fixture_path.parent / p["sourceRaster"]
    verified(tif)

    grid = p["sourceGrid"]
    with rasterio.open(tif) as dataset:
        if (dataset.width, dataset.height) != (grid["width"], grid["height"]):
            raise SystemExit("GeoTIFF dimensions disagree with declaredParameters.sourceGrid")
        opened = {"width": dataset.width, "height": dataset.height,
                  "origin": [dataset.transform.c, dataset.transform.f],
                  "resolution": [dataset.transform.a, dataset.transform.e],
                  "crs": str(dataset.crs), "dtype": dataset.dtypes[0]}

    cutline = shapely.geometry.mapping(shapely.geometry.shape(p["cutline"]))
    cases = [compare_case(case, tif, cutline, grid, p["cutline"]) for case in fixture["output"]]

    return {
        "check": "02-clip",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": "pyodide" in sys.modules or platform.system() == "Emscripten",
            "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__,
            "shapely": shapely.__version__, "geos": shapely.geos_version_string,
            "scipy": scipy.__version__, "numpy": np.__version__,
        },
        "fixture": {"id": fixture["fixtureId"], "sha256": hashlib.sha256(raw).hexdigest(),
                    "rasterSHA256": fixture["input"]["rasterSHA256"],
                    "application": fixture["application"], "operation": fixture["operation"]},
        "openedGrid": opened,
        "cases": cases,
        "agrees": all(c["maskAgrees"] and c["retainedValuesAgree"] is not False for c in cases),
    }


if __name__ == "__main__":
    report = run(ROOT / "fixtures" / "clip-all-touched-001.json")
    out = ROOT / "results" / "check-02-clip.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    for case in report["cases"]:
        o = case["options"]
        label = f"{o['method']} margin {o.get('marginPixels', 0)}"
        verdict = "included sets agree" if case["maskAgrees"] else f"included sets DIFFER in {case['differingCellCount']} cells"
        window = "window agrees" if case["windowAgrees"] else (
            f"window differs: reference {case['referenceWindow']['width']}x{case['referenceWindow']['height']}"
            f" at {case['referenceWindow']['origin']}, Fieldwork {case['fieldworkWindow']['width']}"
            f"x{case['fieldworkWindow']['height']} at {case['fieldworkWindow']['origin']}")
        values = "" if case["retainedValuesAgree"] is None else (
            ", values agree" if case["retainedValuesAgree"] else ", VALUES DIFFER")
        print(f"{label:28s} {verdict}; {window}"
              f" (reference {case['referenceIncluded']} cells, Fieldwork {case['fieldworkIncluded']}){values}")
    print(f"\nrasterio {report['environment']['rasterio']} / GDAL {report['environment']['gdal']}"
          f" · {report['environment']['runtime']}")
    print(f"Wrote {out.relative_to(ROOT)}")
