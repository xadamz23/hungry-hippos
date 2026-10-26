# Hungry Hippos v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Hungry Hippos meal planning and shopping list PWA described in the spec.

**Architecture:** FastAPI renders Jinja templates server-side. htmx swaps partials, and Alpine handles local UI state (sheets, cook mode). Postgres holds all state. List writes `pg_notify`, and an SSE endpoint streams change events so the other phone re-fetches its list. Domain logic (parsing, merging, section guessing, importing) lives in plain `app/services/*` modules that are unit-tested without HTTP.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, SQLAlchemy 2, Alembic, psycopg 3, httpx, recipe-scrapers, anthropic, htmx 2 + htmx-ext-sse, Alpine 3, SortableJS, pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-hungry-hippos-design.md`

## Global Constraints
- Python `>=3.13`. The venv lives at `.venv` (`uv venv --python 3.13`).
- Dev DB: `postgresql+psycopg://hh:hh@127.0.0.1:5433/hungry_hippos`. Tests use the `hungry_hippos_test` database on the same server.
- All front-end libraries are vendored under `app/static/vendor/`, with no CDN at runtime. Every static reference goes through `static_url()`.
- Font is Figtree. Colors are copied exactly from the spec's Design section. Copy is in sentence case.
- Section headers show only the name, with no number and no count.
- Image is `xadamz23/hungry-hippos`, built for `linux/amd64`.

## Review Focus
1. Two phones edit the list at once. Each sees the other's change after the SSE event, and a reconnect after the phone sleeps recovers (htmx-sse reconnects automatically, and each reconnect triggers a full re-fetch). → Test that `/events` emits `list` after a list write.
2. Unparseable ingredient lines ("salt and pepper to taste", "1 (15 oz) can black beans", "½ cup") must never crash parsing. They fall back to name-only or a sensible amount. → Parser tests for each.
3. An import URL that 404s, times out, or has no recipe and no API key shows a readable error on the import screen, not a 500. → Importer and route tests.
4. Merging the same ingredient from two meals in different units shows both ("1 lb + 8 oz"), and nothing is lost. → Merge tests.
5. Deleting a meal that's on the plan or listed as a list item's source must not break the List or Plan pages. Plan entries cascade-delete, and list items keep their name and lose that source. → Route test.

---

### Task 1: Scaffold, config, models, migration, seed
**Files:** `pyproject.toml`, `.gitignore`, `compose.yml` (db service for now, port `127.0.0.1:5433:5432`), `app/__init__.py`, `app/config.py`, `app/db.py`, `app/models.py`, `app/seed.py`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py`, `tests/conftest.py`, `tests/test_seed.py`

**Interfaces (produces):**
- `config.Settings` (pydantic-settings): `database_url`, `anthropic_api_key: str|None`, `anthropic_model="claude-haiku-5-5"`, `tz="America/Detroit"`, `backup_dir="/backups"`. Accessor is `get_settings()`.
- `db.engine`, `db.SessionLocal`, `db.get_session()` (FastAPI dependency that yields a Session), `db.Base`.
- Models: `Section(id, name, color, position)`; `Meal(id, name, servings, total_minutes, steps:text, notes, favorite:bool, source_url, image_url, created_at, updated_at, tags[], ingredients[])`; `Tag(id, name unique)` + `meal_tags`; `Ingredient(id, meal_id→cascade, position, raw, name, name_key, amounts:JSONB list[{"qty":float|null,"unit":str|null}], section_id)`; `ItemSectionMap(name_key PK, section_id)`; `PlanEntry(id, week_start:date, day:date|null, kind in {"meal","leftovers","eat_out"}, meal_id→cascade|null, position, added_to_list:bool, cooked_on:date|null)`; `CookLog(id, meal_id→cascade, cooked_on)`; `ListItem(id, name, name_key, amounts JSONB, section_id, checked, checked_at, created_at)`; `ListItemSource(list_item_id→cascade, meal_id→set null, meal_name)`; `Staple(id, name, name_key, amounts JSONB, section_id, position)`.
- `seed.DEFAULT_SECTIONS: list[tuple[str,str]]` (name, hex) in walk order. Colors: Produce #2E7D32, Bakery #A16207, Deli #8E24AA, Meat & Seafood #C62828, Canned & Soup #BF360C, Pasta & Rice #827717, International #00796B, Baking & Spices #5D4037, Breakfast & Cereal #AD1457, Snacks & Drinks #FF8A65, Household #455A64, Dairy & Eggs #1565C0, Frozen #4FC3F7, Other #757575.
- `seed.ensure_seed(session) -> None` is idempotent and inserts sections only when the table is empty. It also seeds staples Milk (1 gal), Eggs, Bananas (1 bunch), Bread.

- [ ] Write `tests/test_seed.py::test_seed_creates_sections_in_walk_order` (14 sections, positions 0..13, the first is "Produce" and the last is "Other") and `test_seed_is_idempotent`.
- [ ] Run it and confirm it fails (no module).
- [ ] Implement. `conftest.py` creates the test DB if missing, runs `Base.metadata.create_all`, and provides a `session` fixture that TRUNCATEs all tables between tests, plus a `client` fixture (TestClient with `get_session` overridden).
- [ ] Generate `0001_initial` with Alembic autogenerate. Verify with `alembic upgrade head` against the dev DB.
- [ ] Tests pass. Commit.

### Task 2: Ingredient parsing and amounts
**Files:** `app/services/ingredients.py`, `app/services/amounts.py`, `tests/test_ingredients.py`, `tests/test_amounts.py`

**Interfaces:**
- `ingredients.ParsedIngredient(raw, name, name_key, qty: float|None, unit: str|None)` (dataclass).
- `ingredients.parse_line(line: str) -> ParsedIngredient` handles integers, decimals, `1/2`, `1 1/2`, unicode fractions (`½ ⅓ ¼ ¾ ⅔ ⅛`), ranges (`2-3` → upper), and parenthetical sizes (`1 (15 oz) can black beans` → qty 1, unit "can", name "black beans"). It strips trailing `, prep notes` and leading prep words (diced, chopped, minced, sliced, fresh, large, medium, small, shredded is kept). "to taste" yields qty None.
- `ingredients.normalize_unit(s) -> str|None` maps aliases to canonical units: tsp, tbsp, cup, oz, lb, g, kg, ml, l, clove, can, jar, pkg, bunch, head, slice, pinch, gal, qt, pt, stick, bag, box, bottle.
- `ingredients.name_key(name: str) -> str`: lowercase, strips punctuation, naive singular (`ies→y`, `oes→o`, `s→""` except `ss`).
- `amounts.Amount = dict` (`{"qty","unit"}`). `amounts.merge(a: list[Amount], b: list[Amount]) -> list[Amount]` sums matching units; a None qty with the same unit stays None. `amounts.scale(a, factor) -> list[Amount]`. `amounts.fmt(a) -> str` formats as `"3 lb"`, `"1 cup + 2 tbsp"`, `"1½ cups"` (nice fractions, plural units for cup and can), and `""` for an empty or all-None list.

- [ ] Write tests: `test_parse_basic` ("2 lb ground beef" → 2, "lb", "ground beef"), `test_parse_unicode_fraction` ("½ cup milk" → 0.5), `test_parse_mixed` ("1 1/2 cups flour" → 1.5), `test_parse_paren_size`, `test_parse_prep_stripped` ("1 yellow onion, diced" → name "yellow onion"), `test_parse_to_taste`, `test_parse_no_qty` ("salt"), `test_parse_only_amount` ("½ cup" → no crash, name ""), `test_name_key_plural` ("Yellow Onions" == name_key("yellow onion"), "tomatoes"→"tomato", "berries"→"berry", "glass" unchanged). Amount tests: `test_merge_same_unit`, `test_merge_diff_units` (`fmt` → "1 lb + 8 oz"), `test_merge_counts` (3 + 2 → 5), `test_fmt_fraction` (1.5 cup → "1½ cups"), `test_scale`.
- [ ] Run them and confirm they fail. Implement. Confirm they pass. Commit.

### Task 3: Section guessing and learned map
**Files:** `app/services/sections.py`, `tests/test_sections.py`

**Interfaces:**
- `sections.KEYWORDS: dict[str, list[str]]` maps each section name to keywords (for example Produce: onion, garlic, cilantro, pepper, lettuce, banana, apple, potato, tomato, avocado, lime, lemon, carrot, celery …; Meat & Seafood: beef, chicken, pork, sausage, bacon, turkey, shrimp, salmon, kielbasa …; Dairy & Eggs: milk, cheese, cheddar, butter, egg, yogurt, sour cream, cream …; and so on for every section). Multiword phrases beat single words, and the longest match wins ("tomato sauce" → Canned & Soup, beating "tomato" → Produce; "sour cream" → Dairy).
- `sections.guess_section(session, name_key: str) -> Section`: learned map, then keyword match, then "Other".
- `sections.remember(session, name_key, section_id) -> None` upserts.
- `sections.text_color(hex) -> "#fff" | "#10291C"`, whichever gives the higher WCAG contrast.

- [ ] Tests: `test_keyword_guess` (onion→Produce, "ground beef"→Meat, "tomato sauce"→Canned & Soup, "sour cream"→Dairy, "flour tortilla"→International, "frozen peas"→Frozen), `test_unknown_is_other`, `test_learned_wins` (remember tortilla→Bakery, then guess → Bakery), `test_text_color`.
- [ ] Confirm they fail. Implement. Confirm they pass. Commit.

### Task 4: App shell, cache busting, PWA, layout
**Files:** `app/main.py`, `app/assets.py`, `app/templating.py`, `app/templates/base.html`, `app/templates/_nav.html`, `app/static/css/app.css`, `app/static/js/app.js`, `app/static/vendor/{htmx.min.js,sse.js,alpine.min.js,sortable.min.js}`, `app/static/fonts/` (self-hosted Figtree woff2), `app/static/manifest.webmanifest`, `app/static/icons/{icon-192.png,icon-512.png,maskable-512.png,apple-touch-icon.png}`, `app/static/sw.js` served at `/sw.js`, `scripts/make_icons.py`, `tests/test_assets.py`

**Interfaces:**
- `assets.AssetManifest(static_dir: Path)` hashes every file once with `hashlib.sha256` and exposes `.url(path) -> "/static/<path>?v=<10 hex>"`. A missing file raises `KeyError`.
- `templating.templates` (Jinja2Templates) with globals `static_url`, `today()`, and filters `amounts` (→ `amounts.fmt`), `text_color`, `ago` ("6 days ago", "2 weeks ago", "a month ago", "Never made yet").
- Middleware: `/static/*?v=` responses get the immutable header. `/sw.js` gets `no-cache`.
- `base.html` blocks: `title`, `main`, `aside` (desktop only), `sheet`. It includes the mobile bottom nav and the desktop side nav, with `active` set per page.

- [ ] Tests: `test_static_url_has_hash`, `test_hash_changes_when_file_changes` (tmp dir), `test_versioned_static_is_immutable` (GET a versioned URL → header present), `test_manifest_served`, `test_sw_served_at_root`.
- [ ] Confirm they fail. Implement and vendor the assets (download pinned versions: htmx.org@2.0.4, htmx-ext-sse@2.2.2, alpinejs@3.14.8, sortablejs@1.15.6, Figtree from Google Fonts woff2). Port the CSS from the mockups into `app.css`, with mobile first and a `@media (min-width:900px)` two-pane plus side nav.
- [ ] Confirm they pass. Commit.

### Task 5: Shopping list with live sync
**Files:** `app/services/shopping.py`, `app/routers/list.py`, `app/routers/events.py`, `app/templates/list/{page.html,_items.html,_item_sheet.html,_staples.html}`, `tests/test_shopping.py`, `tests/test_list_routes.py`

**Interfaces:**
- `shopping.add_item(session, name: str, amounts: list[Amount], section_id: int|None=None, source: Meal|None=None) -> ListItem` merges into an unchecked item with the same name_key; otherwise it creates a new item with `guess_section`. Calls `notify(session)`.
- `shopping.add_text(session, text) -> ListItem` (quick add, via `parse_line`).
- `shopping.add_meal(session, meal, factor=1.0) -> int` returns the count added.
- `shopping.toggle(session, item_id)`, `update(session, item_id, amount_text, section_id, remember: bool)`, `remove`, `clear_checked`, `clear_all`.
- `shopping.grouped(session) -> list[tuple[Section, list[ListItem]]]` returns only sections that have items, in `position` order. Unchecked items come before checked ones, then sorted by created_at.
- `shopping.progress(session) -> tuple[left:int, total:int]`.
- `shopping.notify(session)` executes `SELECT pg_notify('hh_list','')`.
- Routes: `GET /` → redirect `/list`. `GET /list` (page). `GET /list/items` (partial: progress, staples, sections). `POST /list/add` (text). `POST /list/staple/{id}`. `POST /list/{id}/toggle`. `GET /list/{id}/edit` (sheet). `POST /list/{id}` (save). `POST /list/{id}/delete`. `POST /list/clear-checked`. `POST /list/clear-all`. Each POST returns the `_items.html` partial.
- `GET /events`: an async generator using `psycopg.AsyncConnection` `LISTEN hh_list`. It yields `event: list\ndata: x\n\n` on each notify, and `: ping\n\n` every 15s. Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

- [ ] Tests: `test_merge_on_add` (onion ×1 from Tacos + onion ×2 from Chili → one item, "3", sources [Tacos, Chili]), `test_checked_not_merged`, `test_grouped_walk_order`, `test_quick_add_parses`, `test_update_remember_learns` (the next add of the same name lands in the new section), `test_staple_chip_hidden_when_on_list`, `test_clear_checked`, `test_list_page_renders` (section header shows the name only; assert no "left</" span inside the header), `test_events_emits_on_write` (async: open a listener, call `notify`, receive the event within 2s), `test_meal_delete_keeps_list_item` (Review Focus 5).
- [ ] Confirm they fail. Implement. Confirm they pass. Commit.

### Task 6: Meals (CRUD, list, detail, star, cook)
**Files:** `app/services/meals.py`, `app/routers/meals.py`, `app/templates/meals/{index.html,_rows.html,detail.html,form.html,cook.html,_plan_sheet.html}`, `tests/test_meals.py`

**Interfaces:**
- `meals.save_meal(session, *, meal: Meal|None, name, ingredients_text, steps_text, notes, tags: list[str], servings, total_minutes, favorite, source_url=None, image_url=None, section_overrides: dict[int,int]|None=None) -> Meal` replaces the ingredients from the parsed lines (keeping their order). Each ingredient gets `guess_section`. When `section_overrides` maps a line index to a section id, that section is used and `remember` is called.
- `meals.search(session, q: str|None, favorites: bool, tag: str|None, pick_mode: bool) -> list[MealRow]`, where `MealRow(meal, last_made: date|None, times_made: int, planned_on: PlanEntry|None)`. `pick_mode` sorts favorites first, then oldest last_made (never-made first among favorites), then name. Normal mode sorts by name.
- `meals.ingredients_for_step(meal, step_text, factor) -> list[(name, amount_str)]` uses case-insensitive name-key containment.
- Routes: `GET /meals` (`?q&fav&tag&pick=<date|none>&week=`). `GET /meals/new`. `POST /meals`. `GET /meals/{id}` (desktop: list pane plus detail; mobile: detail only). `GET /meals/{id}/edit`. `POST /meals/{id}`. `POST /meals/{id}/delete`. `POST /meals/{id}/favorite` (returns the star button partial). `POST /meals/{id}/to-list` (adds ingredients to the list and returns a toast). `GET /meals/{id}/cook?servings=`.

- [ ] Tests: `test_create_meal_parses_ingredients`, `test_section_override_learns`, `test_search_by_ingredient` ("beef" finds Tacos), `test_favorites_filter`, `test_pick_mode_order`, `test_favorite_toggle_route`, `test_cook_scales` (servings 6 from 4 → ground beef 1 lb → "1½ lb"), `test_delete_meal_on_plan` (Review Focus 5: the plan page still renders).
- [ ] Confirm they fail. Implement, with templates matching `docs/design/b-screens.html`. Confirm they pass. Commit.

### Task 7: Plan, history, copy week
**Files:** `app/services/planning.py`, `app/routers/plan.py`, `app/templates/plan/{page.html,_week.html}`, `app/templates/more/history.html`, `tests/test_plan.py`

**Interfaces:**
- `planning.week_start(d: date) -> date` (the Monday). `planning.current_week(tz) -> date`.
- `planning.week(session, ws) -> WeekView(days: list[(date, list[PlanEntry])], unscheduled: list[PlanEntry], pending_count: int)`, where pending_count is meal entries with `added_to_list=False`.
- `planning.add_entry(session, ws, day: date|None, kind, meal_id=None, add_to_list=False) -> PlanEntry`.
- `planning.move(session, entry_id, day|None)`, `remove`, `add_week_to_list(session, ws) -> int`, `mark_cooked(session, entry_id, on: date)` (creates a CookLog and sets cooked_on; doing it again undoes it), `copy_week(session, from_ws, to_ws) -> int` (keeps the weekday offset).
- `planning.history(session) -> list[(week_label, list[(date, Meal, times_made)])]`.
- Routes: `GET /plan?week=`. `POST /plan/entries`. `POST /plan/entries/{id}/move`. `POST /plan/entries/{id}/delete`. `POST /plan/entries/{id}/cooked`. `POST /plan/to-list?week=`. `POST /plan/copy-last?week=`. `GET /more/history`.

- [ ] Tests: `test_week_start_monday`, `test_add_and_view_week`, `test_add_week_to_list_only_pending` (running it twice adds nothing the second time), `test_mark_cooked_logs_and_toggles`, `test_copy_last_week`, `test_last_made_from_cooklog`, `test_plan_page_empty_state` (shows "Nothing planned yet").
- [ ] Confirm they fail. Implement. Confirm they pass. Commit.

### Task 8: Recipe import
**Files:** `app/services/importer.py`, `app/routers/importer.py`, `app/templates/meals/import_review.html`, `tests/fixtures/recipe_jsonld.html`, `tests/fixtures/recipe_plain.html`, `tests/test_importer.py`

**Interfaces:**
- `importer.ImportedRecipe(title, ingredients: list[str], steps: list[str], servings: int|None, total_minutes: int|None, image_url, source_url)`.
- `importer.ImportError_(message: str)` (user-facing copy).
- `importer.fetch_html(url) -> str` uses httpx with a 15s timeout, follows redirects, and sends a browser UA. HTTP and timeout errors raise `ImportError_("Couldn't load that page (HTTP 404).")`, and so on.
- `importer.parse_structured(html, url) -> ImportedRecipe|None` uses `recipe_scrapers.scrape_html(html, org_url=url, supported_only=False)` and returns None when there are no ingredients.
- `importer.parse_with_claude(html, url, client=None) -> ImportedRecipe` strips the HTML to text (≤ 60k chars) and calls the Messages API with a forced tool `save_recipe` whose input schema matches ImportedRecipe. Read the `claude-api` skill before writing this.
- `importer.import_url(url) -> ImportedRecipe` tries structured parsing, then Claude if a key is set. Otherwise it raises `ImportError_("This page doesn't have recipe data we can read. Add it by hand instead.")`.
- Routes: `POST /meals/import` (url) renders `import_review.html` with the parsed lines and guessed sections. `POST /meals` (from Task 6) accepts `section_<i>` fields as overrides.

- [ ] Tests: `test_structured_fixture` (title, 7 ingredients), `test_plain_without_key_errors`, `test_plain_with_claude_mock` (fake client returns a tool_use block → recipe), `test_fetch_404_message` (httpx MockTransport), `test_import_route_review_shows_sections`, `test_import_route_error_shown` (200 with the error text, not 500).
- [ ] Confirm they fail. Implement. Confirm they pass. Commit.

### Task 9: More (sections, staples, remembered, backups)
**Files:** `app/routers/more.py`, `app/templates/more/{index.html,sections.html,staples.html,remembered.html}`, `tests/test_more.py`

**Interfaces:**
- Routes: `GET /more`. `GET /more/sections`. `POST /more/sections/order` (ids in order). `POST /more/sections` (add). `POST /more/sections/{id}` (name, color). `GET /more/staples`. `POST /more/staples`. `POST /more/staples/{id}/delete`. `POST /more/staples/order`. `GET /more/remembered`. `POST /more/remembered/{key}/delete`.
- `more.last_backup(dir: Path) -> datetime|None` returns the newest `*.sql.gz` mtime.

- [ ] Tests: `test_reorder_sections_changes_list_order`, `test_add_staple_appears_as_chip`, `test_delete_remembered`, `test_last_backup` (tmp dir), `test_more_shows_ai_status`.
- [ ] Confirm they fail. Implement, with SortableJS posting the order on `onEnd`. Confirm they pass. Commit.

### Task 10: Docker, Compose, build/push, docs
**Files:** `Dockerfile`, `.dockerignore`, `compose.yml` (full), `compose.dev.yml`? (no: dev uses `docker compose up db`), `scripts/backup.sh`, `build-push.sh`, `.env.example`, `README.md`

- Dockerfile: builder stage runs `pip wheel` and the runtime stage runs python:3.13-slim with user `app`, `CMD sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"`, plus a `HEALTHCHECK` on `/healthz`.
- compose: `app` (image `xadamz23/hungry-hippos:latest`, env_file `.env`, depends_on db healthy, `backups:/backups:ro`, port `8000:8000`). `db` (postgres:17, volume `pgdata`, `pg_isready` healthcheck). `backup` (postgres:17 running `scripts/backup.sh`, which loops: `pg_dump | gzip > /backups/hh-$(date +%F).sql.gz`, deletes files older than 14 days, sleeps until 03:00).
- `build-push.sh [--dry-run]`: `docker buildx build --platform linux/amd64 -t xadamz23/hungry-hippos:$(git rev-parse --short HEAD) -t xadamz23/hungry-hippos:latest --push .`. With `--dry-run` it uses `--load` instead of `--push`, then prints `docker image inspect -f '{{.Architecture}}'`.

- [ ] Run `./build-push.sh --dry-run` → arch prints `amd64`.
- [ ] Run `docker compose -p hh-smoke up` with a locally built image. `curl /healthz` returns 200. `/list` renders. Tear it down.
- [ ] Commit.

### Task 11: End-to-end check
- [ ] Seed demo data with `scripts/demo_data.py`: the mockup meals.
- [ ] Use Playwright at 390×844 and 1280×800. Create a meal, plan it, add it to the list, check an item off, and edit a section. Open two browser contexts and confirm a check in one appears in the other via SSE.
- [ ] Compare the screenshots against `docs/design/*`. Fix any drift. Commit.
