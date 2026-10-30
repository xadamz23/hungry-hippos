// Small glue for htmx + Alpine: sheets, toasts, drag-to-reorder, service worker.

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

function closeSheet() {
  const root = document.getElementById("sheet");
  if (root) root.innerHTML = "";
}
window.closeSheet = closeSheet;

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSheet();
});

// `undo` ({url, target, swap}) is a URL to POST that reverses what just happened; its response goes into `target`
// when that's on the page, and is otherwise ignored (or reloads the page itself with HX-Refresh).
let toastTimer;
function toast(message, undo) {
  const root = document.getElementById("toast-root");
  if (!root || !message) return;
  root.innerHTML = "";
  const el = document.createElement("div");
  el.className = "toast glass-strong";
  el.setAttribute("role", "status");
  el.textContent = message;
  if (undo) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "undo";
    btn.textContent = "Undo";
    btn.addEventListener("click", () => {
      el.remove();
      const target = undo.target && document.querySelector(undo.target);
      htmx.ajax("POST", undo.url, target ? { target, swap: undo.swap || "innerHTML" } : { swap: "none" });
    });
    el.appendChild(btn);
  }
  root.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), undo ? 6000 : 2600);
}
window.toast = toast;

// hx-boost and history restores swap the body's contents but not its class, so pages would keep the previous
// page's layout classes (e.g. cook mode showing the tab bar). Each page carries its class on .shell.
function syncBodyClass() {
  const shell = document.querySelector(".shell[data-body-class]");
  if (shell) document.body.className = shell.dataset.bodyClass;
}
document.addEventListener("htmx:afterSettle", syncBodyClass);
document.addEventListener("htmx:historyRestore", syncBodyClass);

// The page is saved for the Back button just before htmx navigates away; leave out an open sheet or toast so
// going back doesn't bring them back (e.g. a meal's sheet after adding it to the plan from that sheet).
document.addEventListener("htmx:beforeHistorySave", () => {
  closeSheet();
  document.getElementById("toast-root")?.replaceChildren();
});

// HX-Trigger sends {"toast": "text"} (detail.value) or {"toast": {"message", "undo": url, "target", "swap"}}.
document.addEventListener("toast", (e) => {
  const d = e.detail;
  toast(d.message || d.value || d, d.undo && { url: d.undo, target: d.target, swap: d.swap });
});
document.addEventListener("close-sheet", closeSheet);

// [data-sortable="/url"]: drag rows by .handle, then POST ids in their new order.
function initSortables(root) {
  if (!window.Sortable) return;
  root.querySelectorAll("[data-sortable]").forEach((el) => {
    if (el._sortable) return;
    el._sortable = Sortable.create(el, {
      handle: ".handle",
      animation: 150,
      onEnd: () => {
        const ids = [...el.querySelectorAll("[data-id]")].map((n) => n.dataset.id);
        const body = new URLSearchParams();
        ids.forEach((id) => body.append("ids", id));
        fetch(el.dataset.sortable, { method: "POST", body, credentials: "same-origin" });
      },
    });
  });
}
document.addEventListener("DOMContentLoaded", () => initSortables(document));
document.addEventListener("htmx:load", (e) => initSortables(e.detail.elt));

// Amount stepper: "2 lb" + 1 → "3 lb"; an empty amount steps up to "1".
function bumpAmount(amt, delta) {
  const m = amt.match(/^(\d+(?:\.\d+)?)(.*)$/);
  if (m) {
    const n = Math.max(0, parseFloat(m[1]) + delta);
    return (n % 1 ? n.toFixed(1) : String(n)) + m[2];
  }
  return !amt.trim() && delta > 0 ? "1" : amt;
}

// "2 lb ground beef" → { amt: "2 lb", name: "ground beef" }. Mirrors parse_line's leading quantity (whole
// numbers, decimals, fractions, unicode fractions, ranges) and unit; `units` comes from unit_words().
const NUM = "\\d+\\s+\\d+/\\d+|\\d+/\\d+|\\d*[½⅓⅔¼¾⅕⅛⅜⅝⅞⅙]|\\d+(?:\\.\\d+)?";
const QTY_RE = new RegExp(`^(?:${NUM})(?:\\s*(?:-|–|to)\\s*(?:${NUM}))?(?=\\s|$)\\s*`);
function splitAmount(raw, units) {
  let rest = (raw || "").trim();
  const m = rest.match(QTY_RE);
  if (!m) return { amt: "", name: rest };
  let amt = m[0].trim();
  rest = rest.slice(m[0].length);
  const [first, ...more] = rest.split(/\s+/);
  if (first && units.has(first.replace(/\.$/, "").toLowerCase())) {
    amt += " " + first;
    rest = more.join(" ");
  }
  // A bare amount ("1 gal") isn't an ingredient; keep it all as the name rather than leave the name empty.
  return rest.trim() ? { amt, name: rest.trim() } : { amt: "", name: raw.trim() };
}

// List quick-add: typing opens a dropdown of matching staples. Typed words are matched against the start of
// each word in a staple's name, counting back from the last word typed and skipping amounts. Only the staples
// that match the most words are shown, so "sour cr" finds Sour cream but not Pie crust, while "2 gal mi"
// still finds Milk. Arrow keys move through the matches and Enter or Tab adds the highlighted one, or the
// only one when just one matches; otherwise Enter adds the typed text.
function quickAddBase() {
  return {
    q: "",
    open: false,
    active: -1,
    limit: 6,
    init() {
      this.$watch("q", () => (this.active = -1));
    },
    // Typed words, last first, without amounts.
    terms() {
      return this.q.toLowerCase().split(/\s+/).filter((w) => w && !/^[\d.\/½¼¾⅓⅔-]+$/.test(w)).reverse();
    },
    // How many typed words, counting back from the last, each start a word in the name. 0 means no match.
    score(name, terms) {
      const parts = name.toLowerCase().split(/\s+/);
      let n = 0;
      for (const t of terms) {
        if (!parts.some((part) => part.startsWith(t))) break;
        n++;
      }
      return n;
    },
    // Names of the best-matching staples, in server order (most added first), capped at `limit`.
    hits() {
      const terms = this.terms();
      const names = [...this.$root.querySelectorAll("#add-suggest [data-name]")].map((b) => b.dataset.name);
      const scored = names.map((name) => [name, this.score(name, terms)]);
      const best = Math.max(0, ...scored.map(([, n]) => n));
      return best ? scored.filter(([, n]) => n === best).map(([name]) => name).slice(0, this.limit) : [];
    },
    shown(name) {
      return this.hits().includes(name);
    },
    options() {
      return [...this.$root.querySelectorAll("#add-suggest [data-name]")].filter((b) => this.shown(b.dataset.name));
    },
    isOpen() {
      return this.open && this.hits().length > 0;
    },
    isActive(el) {
      return this.active >= 0 && this.options()[this.active] === el;
    },
    activeId() {
      return this.active >= 0 ? this.options()[this.active]?.id : null;
    },
    move(delta) {
      const n = this.options().length;
      if (!n) return;
      this.open = true;
      this.active = this.active < 0 && delta < 0 ? n - 1 : (this.active + delta + n) % n;
    },
    // The highlighted suggestion, or the only one when just one matches.
    chosen() {
      if (!this.isOpen()) return null;
      const opts = this.options();
      return opts[this.active] || (opts.length === 1 ? opts[0] : null);
    },
    // Enter or Tab adds the chosen suggestion; otherwise the key does its usual thing.
    pick(e) {
      const el = this.chosen();
      if (!el) return;
      e.preventDefault();
      el.click();
    },
  };
}

document.addEventListener("alpine:init", () => {
  // List item sheet: amount stepper and the "Always put X in <section>" label.
  Alpine.data("itemSheet", () => ({
    sec: "",
    amt: "",
    init() {
      this.sec = this.$el.dataset.section || "";
      this.amt = this.$el.dataset.amount || "";
    },
    bump(delta) {
      this.amt = bumpAmount(this.amt, delta);
    },
  }));

  // List: checked items are hidden by default; the choice is remembered on this device.
  Alpine.data("listView", () => ({
    // Section headings stick below the header, so track its height.
    init() {
      const top = this.$el.querySelector(".top");
      this._ro = new ResizeObserver(() => this.$el.style.setProperty("--list-top-h", top.offsetHeight + "px"));
      this._ro.observe(top);
      // With checked items hidden, a row checked off stays in view briefly so the tick registers before it goes.
      // The row's own hx-on:click has already toggled .done by the time the click reaches here.
      // Swaps of the list (the toggle's response and the SSE refresh it causes) wait until the pause is over.
      this.$el.addEventListener("click", (e) => {
        const row = e.target.closest(".tick")?.closest(".it");
        if (!row || this.showChecked || !row.classList.contains("done")) return;
        row.classList.add("lingering");
        this.lingerUntil = Date.now() + 450;
      });
      this.$el.addEventListener("htmx:beforeSwap", (e) => {
        const wait = this.lingerUntil - Date.now();
        if (wait > 0 && e.detail.target.id === "list-body") e.detail.swapOverride = `innerHTML swap:${wait}ms`;
      });
    },
    lingerUntil: 0,
    destroy() {
      this._ro?.disconnect();
    },
    showChecked: (() => {
      try { return localStorage.getItem("showChecked") === "1"; } catch { return false; }
    })(),
    setShowChecked(on) {
      this.showChecked = on;
      try { localStorage.setItem("showChecked", this.showChecked ? "1" : "0"); } catch {}
    },
  }));

  // Staples page: the filter box hides rows whose name doesn't contain the typed text. Drag handles hide
  // while filtering, since reordering a partial list is confusing.
  Alpine.data("stapleFilter", () => ({
    q: "",
    filtering() {
      return this.q.trim() !== "";
    },
    shows(name) {
      return !this.filtering() || name.toLowerCase().includes(this.q.trim().toLowerCase());
    },
    anyShown() {
      return [...this.$root.querySelectorAll("#staple-rows [data-name]")].some((r) => this.shows(r.dataset.name));
    },
  }));

  Alpine.data("quickAdd", quickAddBase);

  // Pantry check before adding meals' ingredients: the button counts the ticked ones.
  Alpine.data("listReview", () => ({
    n: 0,
    allowNone: false,
    init() {
      this.allowNone = this.$el.dataset.allowNone === "1";
      this.count();
      this.$el.addEventListener("change", () => this.count());
    },
    count() {
      this.n = this.$el.querySelectorAll('input[name="ing"]:checked').length;
    },
    label() {
      if (this.n) return `Add ${this.n} item${this.n === 1 ? "" : "s"}`;
      return this.allowNone ? "Nothing to buy" : "Add to the list";
    },
  }));

  // Meal form: ingredients as rows with the amount split off, added one at a time from the same staple dropdown
  // as the List quick-add. Picking a staple adds just its name; tapping a row opens a sheet to set the amount.
  // Enter in the add box never submits the meal form.
  Alpine.data("ingredientRows", () => {
    const base = quickAddBase();
    return {
      ...base,
      lines: [],
      units: new Set(),
      editing: null,
      draft: { amt: "", name: "" },
      init() {
        base.init.call(this);
        try { this.units = new Set(JSON.parse(this.$el.dataset.units || "[]")); } catch {}
        try {
          this.lines = JSON.parse(this.$el.dataset.lines || "[]").map((raw) => splitAmount(raw, this.units));
        } catch {}
      },
      lineText(l) {
        return [l.amt.trim(), l.name.trim()].filter(Boolean).join(" ");
      },
      add(text) {
        const line = splitAmount(text, this.units);
        if (line.name || line.amt) this.lines.push(line);
        this.q = "";
        this.open = false;
        this.$refs.add.focus();
      },
      enter(e) {
        e.preventDefault();
        const el = this.chosen();
        if (el) el.click();
        else this.add(this.q);
      },
      edit(i) {
        this.editing = i;
        this.draft = { ...this.lines[i] };
        // Focus the sheet, not the Amount box, so a phone keyboard doesn't pop up over the stepper.
        this.$nextTick(() => this.$refs.sheet.focus());
      },
      bump(delta) {
        this.draft.amt = bumpAmount(this.draft.amt, delta);
      },
      save() {
        if (this.draft.name.trim()) this.lines[this.editing] = { amt: this.draft.amt.trim(), name: this.draft.name.trim() };
        else this.lines.splice(this.editing, 1);
        this.close();
      },
      removeEditing() {
        this.lines.splice(this.editing, 1);
        this.close();
      },
      close() {
        this.editing = null;
      },
    };
  });
});

// Photos are shrunk before upload: a phone camera's 4-12 MB picture becomes a few hundred KB, and HEIC becomes JPEG.
const PHOTO_MAX_SIDE = 1600;

async function shrinkPhoto(file) {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
  if (!blob) throw new Error("Couldn't shrink the photo");
  return new File([blob], "photo.jpg", { type: "image/jpeg" });
}

document.addEventListener("alpine:init", () => {
  // Meal form banner: take, pick or link a photo. A taken or picked photo goes in the "photo" file input and
  // image_url is sent empty; a link goes in image_url. Removing clears both.
  Alpine.data("mealPhoto", () => ({
    url: "",
    file: false,
    sheet: false,
    linking: false,
    link: "",
    linkError: "",
    init() {
      this.url = this.$el.dataset.url || "";
    },
    background() {
      return this.url ? `center / cover no-repeat url(${JSON.stringify(this.url)})` : this.$el.dataset.bg;
    },
    openSheet() {
      this.sheet = true;
      this.linking = false;
      this.linkError = "";
      this.$nextTick(() => this.$refs.sheet.focus());
    },
    setFile(file) {
      const files = new DataTransfer();
      if (file) files.items.add(file);
      this.$refs.photo.files = files.files;
      this.file = !!file;
      if (this.url.startsWith("blob:")) URL.revokeObjectURL(this.url);
    },
    async picked(e) {
      const original = e.target.files[0];
      e.target.value = "";
      if (!original) return;
      this.sheet = false;
      let file;
      try {
        file = await shrinkPhoto(original);
      } catch {
        toast("Couldn't open that photo. Try a different one.");
        return;
      }
      this.setFile(file);
      this.url = URL.createObjectURL(file);
    },
    showLink() {
      this.linking = true;
      this.$nextTick(() => this.$refs.link.focus());
    },
    useLink() {
      const link = this.link.trim();
      if (!/^https?:\/\//i.test(link)) {
        this.linkError = "Paste a link that starts with http:// or https://";
        return;
      }
      this.setFile(null);
      this.url = link;
      this.link = "";
      this.sheet = false;
    },
    remove() {
      this.setFile(null);
      this.url = "";
      this.sheet = false;
    },
  }));
});

window.addTag = (btn) => {
  const input = document.getElementById("tags");
  const names = input.value.split(",").map((t) => t.trim()).filter(Boolean);
  if (!names.some((n) => n.toLowerCase() === btn.dataset.name.toLowerCase())) names.push(btn.dataset.name);
  input.value = names.join(", ");
};

document.addEventListener("alpine:init", () => {
  // Keeps the screen awake while on the page. The browser drops the lock when the page is hidden, so take it again
  // on return. Put it on the badge that says so: awake is only true while the lock is really held.
  Alpine.data("screenAwake", () => ({
    awake: false,
    lock: null,
    destroyed: false,
    init() {
      this._onVisible = () => document.visibilityState === "visible" && this.keepAwake();
      document.addEventListener("visibilitychange", this._onVisible);
      this.keepAwake();
    },
    destroy() {
      this.destroyed = true;
      document.removeEventListener("visibilitychange", this._onVisible);
      if (this.lock) this.lock.release();
    },
    async keepAwake() {
      try {
        const lock = await navigator.wakeLock.request("screen");
        // Left the page while the request was pending: don't hold the screen on for the rest of the app.
        if (this.destroyed) return lock.release();
        this.lock = lock;
        this.awake = true;
        lock.addEventListener("release", () => (this.awake = false));
      } catch {
        this.awake = false;
      }
    },
  }));

  // Cook mode: one step at a time.
  Alpine.data("cookMode", () => ({
    i: 0,
    count: 0,
    init() {
      this.count = parseInt(this.$el.dataset.count || "0", 10);
    },
    next() {
      if (this.i < this.count - 1) this.i++;
    },
    prev() {
      if (this.i > 0) this.i--;
    },
  }));
});
