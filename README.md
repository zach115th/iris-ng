# iris-ng

> **Working name.** This is a private fork of [DFIR-IRIS](https://github.com/dfir-iris/iris-web)
> v2.5.0-beta.1, maintained by Zachary Carter for internal use. The name `iris-next` is
> intentionally placeholder — easy to rename when the project's identity is set.

[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](./LICENSE.txt)

A collaborative incident-response platform. Forked from DFIR-IRIS because upstream paused
feature development in late 2024 and stranded `v2.5.0-beta.1` in beta. See
[`FORK.md`](./FORK.md) for attribution + the rationale, and the docs workspace at
[`D:\Documents\IRIS\docs\13-fork-strategy.md`](../IRIS/docs/13-fork-strategy.md) for the
strategy doc.

## Compatibility goal

- **Drop-in compatible with IRIS v2.5.0-beta.1** (API + database) until forced to change.
- Existing n8n workflows and IRIS API clients should continue to work unchanged.
- Upstream bugfixes can be cherry-picked into the `upstream-fixes` branch when they land.

## Run it

```bash
git clone <fork-repo-url>
cd iris-next
cp .env.model .env       # review / change __MUST_BE_CHANGED__ entries
docker compose pull
docker compose up -d
```

UI on `https://<host>` (HTTPS, port 443). First-boot admin password appears in the `app`
container logs:

```bash
docker compose logs app | grep "WARNING :: post_init :: create_safe_admin"
```

Or seed it via `IRIS_ADM_PASSWORD` in `.env` *before* the first start.

## Stack

Five containers: `app` (Flask + SocketIO), `db` (PostgreSQL), `rabbitmq`, `worker`
(Celery), `nginx`. See [`architecture.md`](./architecture.md) for the layered code design
(blueprints → business → datamgmt; cross-layer imports forbidden).

## Branches

- `main` — latest stable, tagged, image-built. Initial commit = pristine v2.5.0-beta.1.
- `develop` — active work. PRs and feature commits land here.
- `upstream-fixes` — created lazily if upstream ever ships a bugfix worth cherry-picking.

## Commit conventions

Inherited from upstream (`CODESTYLE.md`):

- `[ADD]` / `[FIX]` / `[IMP]` / `[DEL]` action prefix.
- With issue: `[#123][FIX] message`.
- Python: f-strings only, one import per line, function names include the module name
  (e.g. `iocs_create`).
- DB schema changes ship an Alembic migration.

## License

LGPL-3.0. See [`LICENSE.txt`](./LICENSE.txt). Modifications must remain LGPL.

## Acknowledgements

DFIR-IRIS by Airbus CyberSecurity (SAS) and the open-source community. Original repo at
<https://github.com/dfir-iris/iris-web>. Sponsored historically by Deutsche Telekom
Security GmbH.
