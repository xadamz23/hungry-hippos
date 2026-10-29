# Hungry Hippos design

## Intent
Adam and his wife use Hungry Hippos to plan family dinners and shop for them at Meijer. Meals go in by hand or by importing a recipe link. Kid favorites get a star. You plan a week, and the ingredients for that week turn into one shopping list, merged and sorted in the order you walk the store. Both phones see list changes live while you shop. The app is installed as a PWA on phones and also works well on a desktop.

**Success:** opening the List tab in the store shows everything in walk order. Checking items off is a single tap. Planning next week takes a couple of minutes.

**Anti-goals:** accounts or logins inside the app (Cloudflare Access handles auth). Per-person attribution. Nutrition or calorie tracking. Cluttered screens.

## Users and environment
- Two adults, both trusted. Cloudflare Access sits in front of the app, which has no auth of its own.
- Production runs in Docker on amd64 with a Postgres container. Images are pushed to Docker Hub as `xadamz23/hungry-hippos`, possibly from an arm64 machine.
- Local development uses a Python venv. Postgres runs from Compose on port 5433, because 5432 is already in use on this machine.

## Features (v1)
### Meals
- Each meal has: name, ingredients (ordered lines), steps (ordered), notes, tags, servings, optional total time, optional source URL and image, and a **favorite star** meaning the kids like it. There is a single star and no separate adult rating.
- Add by hand: ingredients are entered as one free-text line each, and the app parses amount, unit and name. Steps are one per line.
- Import from a link: fetch the page and read its schema.org recipe data. If that yields nothing, fall back to the Claude API when `ANTHROPIC_API_KEY` is set. Before saving, a review screen shows each parsed ingredient with its guessed section. Changing a section there is remembered for next time.
- Meals list: search by name or ingredient. Filter chips for Favorites, All, and each tag. Each meal shows "Last made N ago" and a "+ Plan" button.
- Meal detail: star toggle, tags, notes, last made and times made, ingredients with section color dots, steps, and the actions + Plan, Add to list, Cook, Edit.
- Cook mode: dark full screen with one step at a time and the screen kept on (Wake Lock API). A servings scaler adjusts ingredient amounts. Each step lists the ingredients its text mentions.

### Plan
- A week runs Monday to Sunday, with arrows to move between weeks. Each entry is a meal, **Leftovers**, or **Eating out**. An entry can be on a day or under "Not on a day yet".
- Plan sheet (from a meal): pick a day or No day, this week or next. Checkbox "Also add ingredients to the list".
- "Add ingredients for N meals" opens a pantry check: every ingredient of the week's not-yet-added meals, ticked, so you untick what you already have before adding. The meal page's "Add to list" uses the same check.
- An entry can be marked cooked, which logs to history and feeds "last made".
- Empty week: the days show as usual, and a "Same as last week?" row above Monday offers to **copy last week** onto the same days. Choosing a meal for a day lists kid favorites least recently made first.

### Shopping list
- Items are grouped under full-width colored section headers, ordered by the store's section order. Headers show only the section name, with no number and no count.
- The top shows a big "N of M left" with a progress bar, a quick-add box that parses text like "2 lb apples", and staple chips.
- **Merging:** an ingredient with the same normalized name as an unchecked item merges into it. Amounts in the same unit are summed; different units are listed together ("1 cup + 2 tbsp"). Each item shows its source meals in small text.
- Quantities appear on yellow price-sticker tags. A checked item gets struck through and stays in its section until it's cleared.
- Tapping an item opens a sheet to edit the amount, change the section ("Always put X in Y" is checked by default), remove the item, or save.
- **Staples:** a user-managed list of recurring items, each with a usual amount and a section. They appear as tap-to-add chips under the add box. A chip is hidden while that item is unchecked on the list. Staples are never added automatically.
- **Live sync:** a list change on one device shows up on the other within a second or two, via server-sent events. Who made the change is not shown.
- "Clear checked items" is in the List header and under More. "Clear the whole list" asks for confirmation first.

### Sections and learned aisles
- Seeded order (a typical Meijer walk): Produce, Bakery, Deli, Meat & Seafood, Canned & Soup, Pasta & Rice, International, Baking & Spices, Breakfast & Cereal, Snacks & Drinks, Household, Dairy & Eggs, Frozen, Other.
- Each section has a color, and all 14 defaults are clearly distinct. Header text is white or ink, whichever reads better on that color. Colors are editable.
- Choosing a section for an item: first a learned mapping (normalized name → section), then built-in keyword rules, then Other. Correcting an item's section writes to the learned map.
- Under More: drag to reorder sections, edit color, add or rename sections, and view or delete remembered mappings.

### More
- Store: Section order, Staples, Remembered sections.
- Meals: History (cooked meals grouped by week), and whether AI import is on (the key is configured).
- List: Clear checked items, Clear the whole list.
- System: when the last backup ran (the newest file in the backup directory).

## Design
Direction B, "Grocery utility". Final mockups are in `docs/design/b-grocery-utility.html` and `docs/design/b-screens.html`.
- Font: Figtree (400/500/700/800).
- Colors: white background, spruce ink `#10291C`, secondary text `#4E6357`, rules `#DCE3DE`, wash `#F2F5F3`, checkout green `#178245`, faint green `#E3F2E8`, sticker yellow `#FFD84A`, warn `#B53A2C`.
- Mobile nav is a bottom bar: List / Plan / Meals / More. The active tab has a faint green pill behind the icon, and the icon and label turn green.
- Desktop (≥ 900px) has a dark spruce side nav where the active item gets a pill and light green text. Pages use two panes: Plan with the List beside it, List with the Plan beside it, Meals list with the selected meal beside it.
- Bottom sheets are used for item edit and plan picking.

## Tech
- FastAPI, Jinja2, htmx 2 (with the SSE extension), Alpine.js 3, and SortableJS. All of them are vendored into `app/static/vendor`, not loaded from a CDN.
- SQLAlchemy 2 and Alembic on Postgres 17 through psycopg 3.
- Every static URL goes through `static_url()`, which appends the file's sha256 (first 10 hex characters). Versioned requests get `Cache-Control: public, max-age=31536000, immutable`.
- PWA: manifest, icons, and `/sw.js` at the root scope. The service worker caches versioned static files and does not provide an offline list.
- Live sync: list writes call `pg_notify('hh_list', …)`. `/events` LISTENs and streams `event: list`, with a 15s keepalive. The list container re-fetches when it receives the event.
- Timezone: `TZ` setting (default `America/Detroit`), used to work out "today" and the current week.
- Deployment: multi-stage `Dockerfile` (python:3.13-slim, non-root user) that runs `alembic upgrade head` and then uvicorn with `--proxy-headers`. `compose.yml` has `app`, `db` (postgres:17 with a healthcheck) and `backup` (a nightly `pg_dump` that keeps 14 days and is mounted read-only into the app). `build-push.sh` uses buildx `--platform linux/amd64`, tags with the git sha and `latest`, and pushes. It also supports `--dry-run`.

## Out of scope for v1
Share target, offline list, attribution, nutrition, multiple stores.

## Calls made by the builder (Claude)
- I wrote the ingredient parser in-house instead of using an ML library. It needs fewer dependencies and is predictable.
- Merging matches unchecked items only. Adding an item that's already checked creates a fresh line.
- "Copy last week" was added to the empty week screen.
- Cook mode does not rewrite amounts inside the step text. Instead it lists the scaled ingredients each step mentions.
