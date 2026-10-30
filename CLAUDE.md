# Hungry Hippos

Meal planning and a shared shopping list. FastAPI, Jinja, htmx and Alpine. See `README.md` for setup and deploy.

## UI Conventions

The look is dark glassmorphism in the "Lagoon" palette (blue to teal accent, coral glow). The CSS is plain `app/static/css/app.css` with no Tailwind or build step, so a change shows up on reload.

Glass classes are defined once, in the "glass components" block at the end of `app.css`, with colors as tokens in `:root`. Use them instead of one-off styles or opaque surfaces:

| Class | Use for |
|---|---|
| `.aurora` | The fixed glow layer, rendered once in `base.html`. `body` must stay transparent or it hides the layer. |
| `.glass` | Cards, panels, segmented controls. `.card.glass` is a rounded group of rows; add `.inset` for page margins. |
| `.glass-strong` | Chrome: header, floating nav, sidebar, sheets, toasts. |
| `.glass-chip` | Small chips and buttons on top of images. |
| `.glass-input` | Inputs and the `.add` input-and-button row. |
| `.accent` | Primary buttons. "On" states (active nav, pressed chips, switches, ticks) share its rule, so add new ones to that selector list. |
| `.btn-glass` | Secondary buttons, as `btn btn-glass`. |
| `.pill-radio` | Radio groups: `<label class="pill-radio"><input type="radio">…</label>`. |
| `.glass-card` | Hover lift for meal cards. Off under `prefers-reduced-motion`. |
| `.badge-planned` | Example of a badge on an image: dark tinted glass with a ring, legible over bright photos. |

The phone nav (`.tabs`) is a floating bar that hides while the keyboard is up; desktop uses the sidebar. Anything pinned to the bottom sits above it using `--nav-h` and `--nav-bottom`, as `.detail-actions` and `.toast` do.

Gotchas:

- Write `-webkit-backdrop-filter` by hand before `backdrop-filter`, because nothing adds the prefix here and iOS before 18 needs it.
- `backdrop-filter` makes an element a stacking context, a containing block for `position: fixed` children, and the limit of what its children can blur. So keep fixed elements and sheets out of glass parents, and make dropdowns inside glass near-opaque (see `.suggest`).
- Round cards with `overflow: clip`, not `hidden`, which breaks the sticky section headings.
- Section colors are user-picked. For a heading bar use the `sign_bg` filter, which darkens the color until white text passes AA. Dots get a light ring so dark colors stay visible.
- Keep text at WCAG AA over the glass, including where the aurora is brightest.
