# Fork attribution and rationale

## Origin

This repository (`iris-next`, working name) is a fork of:

- **Upstream:** <https://github.com/dfir-iris/iris-web>
- **Original authors:** Airbus CyberSecurity (SAS) and the DFIR-IRIS community.
- **Original license:** LGPL-3.0 (preserved in this fork).
- **Forked from:** Tag **v2.5.0-beta.1**, upstream commit `a4bfeda` (2025-02-27).
- **Forked on:** 2026-04-28.

The baseline is checked in as commit `15e2981` on the `main` branch (tag
`baseline-v2.5.0-beta.1`) — an exact, unmodified copy of the upstream tree at the
forking point. All fork-specific changes ship as commits on `develop` (and feature
branches off `develop`) so future cherry-picks of upstream fixes apply against an
unmodified baseline.

## Why fork

Upstream development effectively stopped in early 2025:

- Last commit on upstream `master`: 2025-02-27 (`whitekernel`).
- Last "feature" release: **v2.4.13** (2024-12-09, OIDC beta). Everything since is bug
  fixes only.
- **v2.5.0-beta.1** was tagged 2025-03-01 with "heavy improvements in the backend and
  API v2" and never went GA — eight `v2.4.x` patch releases shipped after it without
  promoting the beta.
- Recent commit log is ~90% `[FIX]` (CodeQL, escape, regex). No new features.

This fork exists to continue the platform's evolution while preserving compatibility
with the existing IRIS API surface and on-disk database, so n8n workflows, custom
modules, and external integrations keep working without changes.

## License obligations

LGPL-3.0 is copyleft for the library itself: modifications to LGPL-licensed code in this
repository must also be made available under LGPL when distributed. Linking from a
larger non-LGPL work is permitted under the LGPL exception. See
[`LICENSE.txt`](./LICENSE.txt) for the full text.

## What changed from upstream

Tracked in the git history. To see the full diff against the baseline:

```bash
git diff baseline-v2.5.0-beta.1..HEAD
```

The first divergent commit on `develop` is the **rebrand** — README, image namespaces in
`docker-compose.yml`, version pin in `source/app/configuration.py`, `.bumpversion.cfg`,
plus this `FORK.md` and a `.gitattributes`. None of those touch runtime behaviour.

## Reporting issues / contributing

Internal project — issues and changes flow through the maintainer. Upstream bug reports
should still go to <https://github.com/dfir-iris/iris-web/issues> if they affect the
unmodified parts of the codebase.
