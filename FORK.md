# Fork attribution and rationale

## Origin

This repository (`iris-next`, working name) is a fork of:

- **Upstream:** <https://github.com/dfir-iris/iris-web>
- **Original authors:** Airbus CyberSecurity (SAS) and the DFIR-IRIS community.
- **Original license:** LGPL-3.0 (preserved in this fork).
- **Forked from:** Tag **v2.5.0-beta.1**, upstream commit `a4bfeda` (2025-02-27).
- **Forked on:** 2026-04-28.

All fork-specific changes ship as commits on `main`, which is the active development
branch. The unmodified upstream tree at the forking point is available from upstream
itself at tag `v2.5.0-beta.1`.

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

Summarised in the [README](./README.md) and the
[wiki](https://github.com/zach115th/iris-ng/wiki). To diff this tree against the
upstream fork point directly:

```bash
git remote add upstream https://github.com/dfir-iris/iris-web.git
git fetch upstream --tags
git diff upstream/master..HEAD          # or: git diff v2.5.0-beta.1..HEAD
```

The rebrand itself — README, image namespaces in `docker-compose.yml`, version pin in
`source/app/configuration.py`, `.bumpversion.cfg`, plus this `FORK.md` and a
`.gitattributes` — does not touch runtime behaviour.

## Reporting issues / contributing

iris-ng is a community-maintained open-source project — issues and pull requests are
welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md). Upstream bug reports
should still go to <https://github.com/dfir-iris/iris-web/issues> if they affect the
unmodified parts of the codebase.
