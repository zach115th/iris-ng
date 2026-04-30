# Changelog

All notable changes to `iris-next` (a fork of DFIR-IRIS) are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely, and
versions follow [SemVer 2.0](https://semver.org/) with `+iris-next.<build>` build
metadata appended to the upstream version we forked from.

Inherited upstream changelog (versions ≤ v2.5.0-beta.1) lives in upstream's release
notes: <https://github.com/dfir-iris/iris-web/releases>.

---

## [Unreleased]

Active work on `develop`.

---

## [v2.5.0-beta.1+iris-next.0] — 2026-04-28

Initial fork-identity commit. Establishes `iris-next` as a downstream fork of DFIR-IRIS
v2.5.0-beta.1 without changing runtime behaviour.

### Added
- `FORK.md` — attribution to upstream, forking point, rationale, LGPL-3.0 obligations.
- `.gitattributes` — line-ending normalisation (LF for text, CRLF for `*.bat`/`*.cmd`)
  and binary patterns for shipped wheels/images.
- `CHANGELOG.md` — this file.
- `.gitignore` exception `!.env.model` so the env template stays tracked despite the
  blanket `.env*` rule.

### Changed
- `README.md` rewritten to identify the fork, the drop-in-compatibility goal, the
  branching model (`main` / `develop` / `upstream-fixes`), and inherited upstream commit
  conventions (`[ADD]/[FIX]/[IMP]/[DEL]`).
- `docker-compose.yml` image namespaces switched from `ghcr.io/dfir-iris/iriswebapp_*`
  to `iris-next/*`. Default tag changed from the stale `v2.4.20` to `latest`.
- `.env.model` image-name defaults updated to match.
- `source/app/configuration.py:268` — `IRIS_VERSION` bumped to
  `v2.5.0-beta.1+iris-next.0` (SemVer build metadata).
- `.bumpversion.cfg` — version regex extended to parse the `+iris-next.<build>` suffix;
  `current_version` follows.

### Unchanged (explicitly)
- API routes (legacy `/case|/manage/*` and `/api/v2/*`) — drop-in compatible.
- Database schema and Alembic migrations.
- Runtime logic, modules, hooks, the worker, the frontend.

---

## [baseline-v2.5.0-beta.1] — 2025-02-27 (upstream)

Pristine import of DFIR-IRIS v2.5.0-beta.1 (upstream commit `a4bfeda`).
Tagged `baseline-v2.5.0-beta.1` on `main` as the reference point for upstream
cherry-picks.

[Unreleased]: https://github.com/dfir-iris/iris-web/compare/v2.5.0-beta.1...HEAD
[v2.5.0-beta.1+iris-next.0]: ./
[baseline-v2.5.0-beta.1]: https://github.com/dfir-iris/iris-web/releases/tag/v2.5.0-beta.1
