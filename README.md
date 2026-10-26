# Hungry Hippos

Meal planning and a shared shopping list, sorted in the order you walk through Meijer.

- **List**: ingredients from planned meals, merged ("Onions ×3 — Tacos, Chili"), grouped by store section, with live sync between phones. Includes staples you can add with one tap.
- **Plan**: a Monday–Sunday week. Put meals on days or under "Not on a day yet", add leftovers and eating-out nights, and mark meals cooked.
- **Meals**: add by hand or import from a recipe link. Kid favorites get a star. Each meal has notes, tags, history, and cook mode.
- **More**: section order and colors, staples, remembered sections, history, and backups.

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

Settings come from environment variables or `.env` (see `app/config.py`): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `TZ`, `BACKUP_DIR`.

After changing models, add a migration with `.venv/bin/alembic revision --autogenerate -m "..."`.

## Build and push

```sh
./build-push.sh            # builds linux/amd64 and pushes xadamz23/hungry-hippos:<sha> and :latest
./build-push.sh --dry-run  # builds into the local image store and prints the architecture
```

This works from an arm64 machine because buildx cross-builds through a `docker-container` builder. Log in first with `docker login`.

## Production

On the server, put `compose.yml` and a `.env` (copied from `.env.example`) in the same directory, then run:

```sh
docker compose pull && docker compose up -d
```

- `app` runs migrations on start, then serves on `APP_PORT` (default 8000). Point Cloudflare Tunnel or your proxy at it. The app has no login of its own and relies on Cloudflare Access in front of it.
- `db` is Postgres 17, with data in the `pgdata` volume.
- `backup` writes `hh-YYYY-MM-DD.sql.gz` to the `backups` volume every night at `BACKUP_HOUR` and keeps 14 days. Restore with
  `gunzip -c hh-2026-10-26.sql.gz | docker compose exec -T db psql -U hh hungry_hippos`.

Recipe import reads schema.org recipe data first. If a page doesn't have any and `ANTHROPIC_API_KEY` is set, it asks Claude (`claude-opus-5-5` by default) to extract the recipe.

Static files are served with content-hash URLs (`?v=<sha256>`) and cached as immutable, so a new deploy never shows stale CSS or JS.
