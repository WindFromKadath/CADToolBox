# Maintenance Guide

[中文](MAINTENANCE.zh-CN.md) | English

This project's capabilities are determined jointly by the current code, interface contracts, lock file, and measured results. The API and configuration formats carry no stability commitment yet; when changing them, record the affected scope and verification results.

## Structure

| Directory | Purpose |
|---|---|
| `src/cadtoolbox/contracts.py` | Contracts for parameter provenance, units, axes, thickness, domains, and quality |
| `src/cadtoolbox/geometry/` | I/O, measurement, parametric geometry, trimming, construction, and quality checks |
| `src/cadtoolbox/solver/` | Native solving sessions, constraint models, and dimension driving |
| `src/cadtoolbox/raster/` | Controlled outlines and pixel-primitive candidates |
| `src/cadtoolbox/workflows/` | Chains tools into acceptable scenario flows |
| `tests/`, `examples/` | Synthetic regression and publicly runnable examples |
| `scripts/` | UV environment, example preparation, project entries, and privacy checks |
| `docs/` | Usage guide, public capability catalog, and code API index |

Real cases, source manifests, and internal acceptance scripts under `configs/` are used only in the maintainer's workspace. They are not distributed with the public repository, and capability status must not be fabricated from missing provenance.

## Changes and verification

1. Check the affected implementation, current contracts, and capability boundaries. Changes to interfaces, units, axes, thickness, or construction strategies must state the calling convention and impact.
2. Use the UV locked environment. Choose normal, boundary, or failure cases for new behavior; backend upgrades and geometry quality-gate changes should actually run the related flows.
3. After changes, run the affected checks; prepare the full synthetic regression with the commands below. When updating the guide, capability boundaries, and API index, check against the real code.
4. Before committing, review the staged diff, author/committer identity, commit message, and input provenance, and perform the checks in the [security statement](../SECURITY.md). Write reports outside the repository.
5. Commit by feature, fix, or documentation scope; branches may use `codex/<topic>`. After pushing, read back the remote version, files, and repository settings.

```powershell
.\scripts\uv.ps1 sync --locked --check
.\scripts\uv.ps1 run --locked python scripts/prepare_examples.py
.\scripts\uv.ps1 run --locked pytest -q
.\scripts\uv.ps1 run --locked cadtoolbox demo-io --output artifacts/maintenance-demo
```

Use a new name for the output directory. Under-constraint, conflicts, over-budget fitting, fusion, or read-back failures must keep their failure status; success must not be obtained by silently loosening gates.

## Documentation and data

The root README is user-facing: purpose, installation, examples, boundaries, and license. Author learning records, internal trade-offs, migration tasks, and release audits are kept separately on the maintainer's machine and do not enter the public Git tree; the author maintains their own understanding and parameter confirmations.

Git manages only the code and documentation within the release scope. Ignored configs, models, images, failed inputs, and audit logs require separate controlled backups. Public example installation does not overwrite these files. The project uses the [MIT License](../LICENSE); rights in inputs and third-party dependencies must be checked separately.
