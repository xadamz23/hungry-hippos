# Hungry Hippos

Meal planning and a shared shopping list, sorted in the order you walk through Meijer.

- **List**: ingredients from planned meals, merged ("Onions ×3 — Tacos, Chili"), grouped by store section, with live sync between phones. Includes staples you can add with one tap.
- **Plan**: a Monday–Sunday week. Put meals on days or under "Not on a day yet", add leftovers and eating-out nights, and mark meals cooked.
- **Meals**: add by hand or import from a recipe link. Kid favorites get a star. Each meal has notes, tags, history, and cook mode.
- **More**: section order and colors, staples, remembered sections, and history.

Design and decisions are in [`docs/superpowers/specs/2026-10-26-hungry-hippos-design.md`](docs/superpowers/specs/2026-10-26-hungry-hippos-design.md). The original mockups are in `docs/design/`.

## Local development

Requires Python 3.13 ([uv](https://docs.astral.sh/uv/)) and Docker.

```sh
uv venv --python 3.13 .venv
uv pip install -e '.[dev]' --python .venv/bin/python
docker compose up -d db                 # Postgres on 127.0.0.1:5433
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload # http://127.0.0.1:8000
```

Tests use a separate `hungry_hippos_test` database on the same server, which they create automatically:

```sh
.venv/bin/pytest
```

Settings come from environment variables or `.env` (see `app/config.py`): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `TZ`.

After changing models, add a migration with `.venv/bin/alembic revision --autogenerate -m "..."`.

## Deploy

The image is built on the dev machine (arm64) for amd64 and pushed to Docker Hub as `docker.io/xadamz23/hungry-hippos`. Image tags follow git tags. Run the tests first, because the script doesn't. Then:

```sh
scripts/deploy-hungry-hippos-from-arm64.sh v0.1.0
```

The script refuses to run with uncommitted changes. It tags HEAD and pushes the tag, then builds `:<tag>` for amd64 and pushes it (no `:latest`). Last, it SSHes to the server as root and runs `/home/dockerapps/hungry-hippos/update-app.sh <tag>`.

### Prod server

`scripts/update-app.sh` lives on the server at `/home/dockerapps/hungry-hippos/update-app.sh`, next to a `.env` (start from `.env.example`). The server runs its own copy, so re-copy it whenever it changes.

- If the running container already has the requested tag, the script does nothing.
- Otherwise it writes `docker-compose.yaml` pinned to that tag and runs `docker compose up -d`. Only the app container is recreated, and `db` keeps running.
- To roll back, run the script with an older tag. Migrations only run forward, so roll back only to a release that has the same migrations.

The app publishes no ports. cloudflared reaches it at `http://hungry-hippos:8000` over the external `cf-tunnel` network, and Cloudflare Access sits in front of it. The app has no login of its own.

`db` is Postgres 17, with data in the `hungry-hippos_pgdata` volume. Nothing in the stack backs it up. To take a dump from the server directory:
`docker compose exec -T db pg_dump -U hh --no-owner hungry_hippos | gzip > hh-$(date +%F).sql.gz`

The repo's `compose.yml` is for local development (the db) and isn't used on the server.

Recipe import reads schema.org recipe data first. If a page doesn't have any and `ANTHROPIC_API_KEY` is set, it asks Claude (`claude-opus-5-5` by default) to extract the recipe.

Static files are served with content-hash URLs (`?v=<sha256>`) and cached as immutable, so a new deploy never shows stale CSS or JS.
