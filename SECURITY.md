# Security and Privacy Maintenance

[中文](SECURITY.zh-CN.md) | English

This repository publishes code, tests, lock files, usage documentation, and safe examples. Committers are responsible for verifying source permissions, attribution, and the actual staged version.

## Content scope

| May enter Git | Kept controlled; does not enter the public Git tree |
|---|---|
| Implementation, tests, scripts, UV lock file, safe examples | Virtual environments, caches, build artifacts |
| Public usage docs, capability and API indexes | Author learning records, internal tasks, and release audits |
| Pattern-checking tools and disabled Hook templates | Original models/images, real cases, source manifests, logs, and sessions |
| Confirmed public attribution | Credentials, personal emails/names/hosts, local absolute paths, and internal addresses |

Ignore rules do not remove tracked content or history, and provide no encryption, access control, or backup. Images, PDFs, Office files, models, archives, LFS, and submodules require separate review of content, metadata, and source permissions; pattern scans do not cover them.

## Pre-commit checks

Use the confirmed public alias and GitHub noreply identity, set only this repository's identity, and do not change the global identity. Environment variables, amend, cherry-pick, and explicit author parameters can also change the actual attribution.

Stage precisely and read the diff. Use PowerShell 7.2+:

```powershell
git status --short
git diff --cached
pwsh -NoProfile -File scripts/Invoke-RepoPrivacy.ps1 -Mode Staged -CommitMessagePath <commit-message-file-outside-repo> -ReportPath <report-file-outside-repo>
pwsh -NoProfile -File scripts/Invoke-RepoPrivacy.ps1 -Mode Index -ReportPath <report-file-outside-repo>
pwsh -NoProfile -File scripts/Invoke-RepoPrivacy.ps1 -Mode History -ReportPath <report-file-outside-repo>
```

Replace placeholder paths before running. Additional private identifiers are passed via a JSON array outside the repository through `PRIVACY_TERMS_FILE`; that list must not be committed. The checker and public rules live in `.privacy-tools/`; the tool scans only local objects and uploads nothing.

| Exit code | Action |
|---|---|
| 0 | No blocking or pending-review candidates found in this scope; attachments and provenance still require manual review |
| 1 | Fix blocking items, re-stage, and re-check |
| 2 | Review the exact versions of emails, binaries, or large files; record reasons and dates |
| 3 | Check incomplete; fix the environment or configuration and rerun |

Hook templates are disabled by default; before enabling, check `core.hooksPath` and existing hooks, and do not overwrite existing settings. Before first publication, new branches, or tag pushes, check the full history to be released; after pushing, read back the remote content, attribution, license, and visibility.

Lightweight pattern checks are not a complete secret audit. GitHub secret scanning and push protection can serve as additional checks, but cannot replace local content and history review.

## When a leak is found

Revoke or rotate valid credentials first, then handle content and history. Keep controlled backups and desensitized evidence, and implement remediation within an explicitly authorized scope. After deletion, recreation, or history rewriting, old object entry points must still be verified; access failure, cache clearing, and disappearance of all copies are different conclusions.

Private identifiers, keys, old sensitive commit hashes, and raw responses must not be copied into public Issues, PRs, or logs. Security issues get only desensitized descriptions and reviewable minimal reproductions; internal release audits stay in controlled locations.
