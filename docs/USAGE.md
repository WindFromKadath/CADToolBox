# ToolBox Usage Statement and Guide

[中文](USAGE.zh-CN.md) | English

This toolbox currently serves local development, geometric construction, controlled data processing, and verification. The API, configuration, and backend dependencies may still change across versions. Callers must specify input units, axes, parameter provenance, result types, and error tolerances; output reports keep failure and candidate states and do not automatically confirm design dimensions.

## Environment and basic entries

In the project root, follow the [README](../README.md) to install Python 3.13 with `scripts/uv.ps1` and run `sync --locked --managed-python`. The actually locked backends are in `uv.lock`; run commands with this project's environment. Prepare safe fixtures with `python scripts/prepare_examples.py`; re-running preserves existing configuration.

| Task | Command (prefixed with `.\scripts\uv.ps1 run --locked cadtoolbox`) | Inputs and outputs |
|---|---|---|
| View help | `--help`; add `--help` to subcommands | No original models required |
| Minimal geometry flow | `demo-io --output artifacts/demo-01` | Auto-synthesizes DXF, checks parsed volume, reads STEP back |
| Inspect STEP | `inspect-step inputs/model.step --kind Solid --axis 0 0 0 1 0 0` | Explicit-axis measurement and import type |
| Round-trip STEP | `roundtrip-step inputs/model.step artifacts/rechecked.step --kind Solid` | Refuses overwrite by default; Compound requires an explicit solid count |
| Inspect DXF | `inspect-dxf inputs/profile.dxf --unit mm --layers PROFILE` | Consistent unit declaration; select pure-outline layers |
| Real solving | `solve-sketch examples/solver-case.json` | Separate process; native status/DOF/residuals |
| Solution-driven solid | `build-solved-profile examples/solver-case.json --output artifacts/solved-01` | Builds STEP/DXF from the actual solution; the normal example parses to 48000 mm³ |
| Surface blade | `build-surface-blade configs/surface-case.json --output artifacts/surface-01` | Local controlled case; angle field/budget/closure/read-back |
| Rotor | `build-rotor configs/rotor-case.json --output artifacts/rotor-01` | Local controlled input; intermediate audit and final topology gates |
| Controlled image solid | `build-raster-profile artifacts/pixels/single.json --output artifacts/raster-01` | Synthetic or reviewed images with explicit mm calibration |
| Pixel candidates | `extract-image-candidates inputs/candidates.json --output artifacts/candidates-01` | Image path+sha256, primitive_settings; JSON/PNG/SVG output, not mm constraints |
| Manifest & provenance checks | `list-tools`, `list-methods`, `show-tool T013`, `show-method M011`, `check --sources` | Maintainer-local configs manifests; fresh clones do not include original sources/proofs |

The CLI restricts outputs to the project root; inputs may come from controlled external directories. `--root` is a root-level option and must precede the subcommand. Scenario output directories must not exist; use a new relative directory on repeat runs. `inspect-dxf` produces no geometry file. A successful STEP import alone does not prove quality.

```powershell
.\scripts\uv.ps1 run --locked python examples/generate_raster.py --output artifacts/pixels
.\scripts\uv.ps1 run --locked cadtoolbox build-raster-profile artifacts/pixels/single.json --output artifacts/raster-single
.\scripts\uv.ps1 run --locked cadtoolbox build-raster-profile artifacts/pixels/three-regions.json --output artifacts/raster-three
```

`examples/raster-*-case.json` are regression/calibration templates; zero digests and placeholder images in image_input cannot pass the provenance gate. The generator produces synthetic pixels with real SHA-256; substituting actual images requires updating the hashes accordingly and independently verifying the calibration.

## Python API

Import from the new package; import `cadtoolbox.geometry` first to set up the project cache, then use the backends. For actual parameters, modules, and fields, see the [code-extracted API index](api-index.json); for per-item capability boundaries, see the [project content record](project-status.json).

```python
from pathlib import Path
import cadtoolbox.geometry
import cadquery as cq
from cadtoolbox.contracts import Axis, ShapeExpectation, ShapeKind
from cadtoolbox.geometry.measure import measure
from cadtoolbox.geometry.io import export_step

axis = Axis((0, 0, 0), (1, 0, 0))
solid = cq.Solid.makeCylinder(10, 20, axis.origin_mm, axis.direction)
report = measure(solid, axis)
expected = ShapeExpectation(ShapeKind.SOLID, 1)
export_step(solid, Path('artifacts/api-cylinder.step'), expected)
```

Python API callers are responsible for controlling write paths; the CLI's project-root restriction does not cover direct API calls.

| Tool ID | Code entry | Usage scope |
|---|---|---|
| T001/T002/T012 | `geometry.io.load_step/export_step`, `geometry.measure.measure`, `geometry.quality.validate_shape` | Type/count, axial dimensions, topology, and read-back |
| T003 | `contracts.Parameter/Axis/Frame/Thickness/DomainSpec/QualityPolicy` | Contracts for parameter provenance, units, right-handed coordinates, thickness, and error |
| T004 | `geometry.io.load_dxf` | Closed XY LINE/ARC/CIRCLE/POLYLINE (with bulge)/SPLINE/ELLIPSE; partially migrated |
| T005/T009 | `geometry.domains.axisymmetric_channel/projected_channel/material_domain/trim_solid/trim_bspline_face` | Domain types kept separate; all trimming components preserved |
| T006/T008 | `geometry.parametric`, `theta_fields.build_field`, `twisted_solid.build_twisted_solid` | Supported base surfaces and fields; independent fitting, shared-boundary closure |
| T007 | `geometry.blades.build_radial_blade` | Two-circle intersection/angle law; arc-length or chord-length total thickness |
| T010/T011 | `geometry.assembly`, `rotor_junction` | Two-end rotor-feature recognition, strict edge counts, arbitrary-axis arrays, and unique-component fusion |
| T013 | `solver.sketch.solve_sketch`, `solver.model.drive_dimensions`, `workflows.solved_profile` | Geometry generated only when normal, fully determined, redundancy-free, and residual-qualified |
| T014/T015 | `raster.profiles/regions/primitives`, `workflows.raster.run_raster` | Controlled outlines or unconfirmed pixel candidates |
| T016 | Report and image export of each flow | Partially migrated; interactive UI / other historical report formats not finished |

## Configuration conventions

- Public solver examples are `examples/solver-*.json`; original real cases stay in local configs. `schema_version=1`, `unit=mm`; in a sketch, points/lines/circles/constraints declare IDs, initial values, connection relations, and constraints separately. Dimension parameters carry name/value/unit/source/status; datums carry coordinates, source/status.
- `geometry.profile_lines` specifies the continuous closed order; `hole_circles` lists holes explicitly; `extrusion_mm` and frame specify the extrusion and local axes. Initial guesses must not replace dimensional constraints; `drive_dimensions` modifies constraint values.
- Image configs use image_input's relative path and actual sha256; source_parameter_references, if provided, must also be read and matched against real files. Mono/three-color profile_settings carry explicit calibration and simplification budgets; three-color naming and adjacency have fixed requirements.
- Surface configs include base, field, frame, fit, sewing, quality_policy; formulas, radial samples, two-end laws, and C1 meshes are used per implementation constraints. `step_face` will error. Source cases are not public examples; consult private sources before restoring real parameters.
- Rotor source configs must not be generalized to all rotors; in-memory modeling mode and intermediate STEP audits are separate; fillet edge counts, final solid counts, short-edge, and degeneracy requirements stay explicit.

Provenance status `derived` means derived from documentation, computation, or controlled reference — it does not mean the user has confirmed it. The assumed/missing/conflicting gates and field validation should be preserved.

## Failures and troubleshooting

| Symptom | Check and action |
|---|---|
| Manifest commands lack configs / proofs | Use the public static content record; the maintainer restores controlled local configs. Do not fabricate verified records |
| Dependency or DLL not found | Project UV `sync --locked`; check that `.venv` and the current platform are used; missing dependencies must not be recorded as feature passes |
| Output directory exists | Use a new directory; keep the old report for audit; STEP overwrite only via explicit `--overwrite` |
| DXF unit conflict / text entities | Verify units; select pure-outline layers; do not silently drop unknown entities or unclosed edges |
| Under-constraint, conflict, redundancy | Read DOF, failed_constraint_ids, and residuals; add correct constraints; never output determined solids from failed coordinates |
| Hash mismatch | Check the input version and re-review provenance; do not just replace the hash to mask content changes |
| Fit, fillet, fusion, or read-back failure | Keep report/intermediate models; check domains, thickness, budgets, edge strategies, and topology; do not silently loosen gates |
| Candidate looks like the drawing | Geometry type, calibration, and connectivity still need human confirmation; candidate scores are not confidence probabilities or design confirmation |

Help returns 0 normally; directory/contract/geometry errors usually return 2; check validation failures return 1. Solve failures or under-constraint return 2; programming exceptions keep their stack traces. Before sharing reports externally, handle paths, configuration snapshots, metadata, and raw inputs per the [privacy statement](../SECURITY.md).
