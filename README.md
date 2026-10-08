# Fieldwork Validation Lab

Notebooks that **independently recompute** Fieldwork's spatial results in Python
and report agreement or disagreement with a stated tolerance.

The design record lives in the Fieldwork repository, not here:
[`docs/experiments/41-validation-lab.md`](../fieldwork/docs/experiments/41-validation-lab.md).
Findings are written up there too, beside the widget they concern. This
repository holds the notebooks, the fixtures and the machine-readable results.

## The rules that make it worth running

- The lab does not import or re-execute Fieldwork's JavaScript.
- Fieldwork does not call, embed or depend on the lab.
- Neither side shares a numerical module with the other.
- A notebook recomputes from a fixture's `declaredParameters` and `input` only.
  Fieldwork's intermediate values are deliberately absent from fixtures.
- Every fixture is identified by SHA-256 and verified before comparison.
- The tolerance is stated in the notebook before the comparison runs.
- Disagreements are published with both values, never tuned away.

A notebook that reused the implementation under test would measure nothing.

## Layout

    content/
      00-kernel-check.ipynb          which packages this kernel really has, and their versions
      01-reproject-vs-pyproj.ipynb   check 01
      02-clip-vs-rasterio.ipynb      check 02
      checks/                        the comparison, importable and runnable headlessly
      fixtures/                      exported from Fieldwork, with .sha256 beside each
      results/                       recorded reports, including the environment that produced them

## Running

In a browser, build the static site and open `00-kernel-check.ipynb` first:

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    jupyter lite build --contents content --output-dir _output
    python3 -m http.server --directory _output 8000

Headlessly in CPython, which is faster for iterating but **is not the browser
kernel**:

    pip install -r requirements-checks.txt
    python content/checks/check_01_reproject.py
    python content/checks/check_02_clip.py

Either way the recorded report names the runtime, so a CPython result is never
mistaken for a Pyodide one.

## Fixtures

Fixtures are produced on the Fieldwork side, which is the direction the boundary
allows. From a Fieldwork checkout:

    node scripts/export-validation-fixture.mjs reproject-utm35s-001 ../validation-lab/content/fixtures
    node scripts/export-validation-fixture.mjs clip-all-touched-001 ../validation-lab/content/fixtures

That writes each fixture, any binary sidecar such as a GeoTIFF, and a `.sha256`
for every file. Regenerate rather than edit: a fixture
edited by hand no longer describes what the application did.

## Results so far

| Check | Operation | Reference | Result |
| --- | --- | --- | --- |
| 01 | Reproject input, WGS84 UTM 35S to CRS84 | `pyproj` 3.8.0 / PROJ 9.8.1 | **Agrees.** Maximum separation 6.70 × 10⁻⁵ m over 9 points against a 1 mm tolerance |
| 02 | Clip raster, cell centre inside, margin 0 | `rasterio` 1.5.2 / GDAL 3.12.2 | **Agrees exactly.** Same window, same 132 cells, same retained values |
| 02 | Clip raster, all touched, margin 0 | `rasterio` 1.5.2 / GDAL 3.12.2 | **Differs.** Fieldwork includes 35 cells GDAL excludes and none the other way; all 35 sit beside a pixel-aligned cutline coordinate |
| 02 | Clip raster, all touched, margin 1 | dilation model | **Inconclusive by construction.** `rasterio` has no margin parameter; the 61-cell gap is against a 3 × 3 dilation model, not a validated reference |

Both checks ran in CPython 3.13.3 on macOS arm64, **not** in Pyodide, so the
first acceptance criterion in the design record is unmet for a browser kernel
and these figures should be reproduced there.

Check 01's residual is explained: Fieldwork stores coordinates rounded to nine
decimal places, whose worst case is about 7.8 × 10⁻⁵ m at the fixture's
latitudes, above the observed separation. The agreement is limited by the
documented rounding, not by the projection.

Check 02's disagreement is also explained, and is a finding rather than a defect
report. Fieldwork's all-touched test measures distance to a **closed** cell
rectangle, so a cutline edge running exactly along the border between two cells
touches both, while GDAL's ALL_TOUCHED assigns it to one; a 1e-9 pixel window
pad widens the crop by a further cell. The difference is one-sided, so an
all-touched clip here retains more boundary cells than a GDAL-derived one. For
count-valued rasters such as population that inflates any total. The write-up
lives in the Fieldwork repository at `docs/experiments/29-raster-edge-inclusion.md`.

Next: polygon area against `pyproj.Geod`, where disagreement is expected because
Fieldwork records a spherical method and `Geod` is ellipsoidal.

## What a passing check does not establish

That the declared CRS was the right one for a file, that the source coordinates
were recorded correctly, or that the operation suits a public-health question.
Those are separate judgements and stay in Fieldwork's own records.

Licensed under Apache License 2.0, matching Fieldwork.
