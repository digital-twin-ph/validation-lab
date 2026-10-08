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

Either way the recorded report names the runtime, so a CPython result is never
mistaken for a Pyodide one.

## Fixtures

Fixtures are produced on the Fieldwork side, which is the direction the boundary
allows. From a Fieldwork checkout:

    node scripts/export-validation-fixture.mjs ../validation-lab/content/fixtures/reproject-utm35s-001.json

That writes the fixture and its `.sha256`. Regenerate rather than edit: a fixture
edited by hand no longer describes what the application did.

## Results so far

| Check | Operation | Reference | Result |
| --- | --- | --- | --- |
| 01 | Reproject input, WGS84 UTM 35S to CRS84 | `pyproj` 3.8.0 / PROJ 9.8.1 | **Agrees.** Maximum separation 6.70 × 10⁻⁵ m over 9 points against a 1 mm tolerance |

Check 01 ran in CPython 3.13.3 on macOS arm64, **not** in Pyodide, so the first
acceptance criterion in the design record is not yet met for a browser kernel.
The residual is explained: Fieldwork stores coordinates rounded to nine decimal
places, whose worst case is about 7.8 × 10⁻⁵ m at the fixture's latitudes, above
the observed separation. The agreement is therefore limited by the documented
rounding, not by the projection.

Next: all-touched raster clipping against `rasterio.mask`, and polygon area
against `pyproj.Geod`, where disagreement is expected because Fieldwork records
a spherical method and `Geod` is ellipsoidal.

## What a passing check does not establish

That the declared CRS was the right one for a file, that the source coordinates
were recorded correctly, or that the operation suits a public-health question.
Those are separate judgements and stay in Fieldwork's own records.

Licensed under Apache License 2.0, matching Fieldwork.
