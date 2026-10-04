# CADToolBox

[中文](README.md) | English

A Python CAD toolbox and modeling-methods library providing STEP/DXF processing, parametric geometry, 2D constraint solving, and controlled image-outline processing. It connects inputs to verifiable geometric output through explicit units, axes, parameter provenance, and quality checks.

Current version: `0.1.0`. The API and configuration formats are still evolving. Lengths are uniformly in mm and angles in rad; Face, Solid, and Compound are explicitly distinguished, along with expected solid counts.

## What it can do

| Capability | Current support |
|---|---|
| Files & quality checks | STEP import, export, and read-back; axial measurement; solid-count, short-edge, and degeneracy checks |
| DXF outlines | Closed XY outlines supporting LINE, ARC, CIRCLE, 2D polylines with bulge, SPLINE, and ELLIPSE |
| Parametric construction | Revolve, extrude, arc/angle-law blades, domain clipping, arrays, and fusion |
| Surfaces & blades | Four-boundary Coons, supported 2D twist fields, fitting within budget, and shared-boundary closure |
| 2D constraint solving | Runs slvs in a separate process; reports DOF, conflicts, and residuals; solved coordinates drive CAD/DXF |
| Image processing | Controlled mono/three-color outlines; pixel-line, circle, and arc candidates with JSON/PNG/SVG output |
| Modeling methods | Applicability conditions for parameter provenance, domain selection, fitting budgets, construction strategies, and failure handling |

For detailed capabilities and interfaces, see the [tool/method catalog](docs/project-status.json), the [usage guide](docs/USAGE.md), and the [API index](docs/api-index.json).

## Installation and first run

Requires Git, uv, and PowerShell. The currently verified environment is Windows with Python 3.13; dependency versions are pinned by `uv.lock`. Project scripts keep the environment and caches inside the project directory.

```powershell
git clone https://github.com/WindFromKadath/CADToolBox.git
Set-Location -LiteralPath 'CADToolBox'
.\scripts\uv.ps1 python install 3.13 --no-bin --no-registry
.\scripts\uv.ps1 sync --locked --managed-python
.\scripts\uv.ps1 run --locked cadtoolbox --help
.\scripts\uv.ps1 run --locked cadtoolbox demo-io --output artifacts/my-first-demo
```

`demo-io` automatically generates synthetic DXF and STEP files, checks the parsed volumes, and reads the results back. The output directory must be a new directory; use a different name on each run. The CLI returns a JSON report.

Run the public solver example:

```powershell
.\scripts\uv.ps1 run --locked cadtoolbox solve-sketch examples/solver-case.json
.\scripts\uv.ps1 run --locked cadtoolbox build-solved-profile examples/solver-case.json --output artifacts/my-solved-profile
```

For image-example generation, the Python API, configuration fields, and failure troubleshooting, see the [usage guide](docs/USAGE.md).

## Running the regression suite

```powershell
.\scripts\uv.ps1 run --locked python scripts/prepare_examples.py
.\scripts\uv.ps1 run --locked pytest -q
```

The preparation script installs safe test fixtures only when configuration is missing, and preserves existing configuration. Tests use synthetic data; real engineering inputs and source-acceptance evidence are not distributed with the repository.

## Usage boundaries

- DXF currently handles closed XY outlines; automatic interpretation of nested holes across layers is not supported.
- Blades support arc-length or chord-length thickness; normal uniform-thickness offsets, parametric arbitrary STEP base surfaces, and global self-intersection proofs are not yet supported. Fillet-edge recognition applies to declared two-end rotor features.
- The solver covers only the implemented entities and constraints; it does not provide full engineering-drawing semantic compilation.
- Image candidates keep pixel units and a to-be-confirmed status; they do not automatically become engineering dimensions. General OCR, complete dimension chains, and arbitrary drawing-to-STEP conversion are not yet implemented.
- `list-tools`, `list-methods`, and provenance checks depend on the maintainer's local manifests. Public users can consult the static tool/method catalog and use the standalone CLI, API, and safe examples.

Callers must provide explicit units, axes, calibration, and parameter provenance. Missing, conflicting, or unapproved assumptions block deterministic geometry; passing geometry checks does not replace engineering design confirmation.

## Maintenance and license

For contribution and acceptance requirements, see the [maintenance guide](docs/MAINTENANCE.md); for commit scope and privacy checks, see the [security statement](SECURITY.md). Original models, images, private configuration, internal learning records, environments, caches, and generated artifacts do not enter public version control.

The project code is licensed under the [MIT License](LICENSE). Third-party dependencies and input data follow their own licenses and provenance permissions.
