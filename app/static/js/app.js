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

let toastTimer;
function toast(message) {
  const root = document.getElementById("toast-root");
  if (!root || !message) return;
  root.innerHTML = "";
  const el = document.createElement("div");
  el.className = "toast";
  el.setAttribute("role", "status");
  el.textContent = message;
  root.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 2600);
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

document.addEventListener("toast", (e) => toast(e.detail.value || e.detail));
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
    // Section headings stick below the header, so track its height (it shrinks while typing hides the staples).
    init() {
      const top = this.$el.querySelector(".top");
      this._ro = new ResizeObserver(() => this.$el.style.setProperty("--list-top-h", top.offsetHeight + "px"));
      this._ro.observe(top);
    },
    destroy() {
      this._ro?.disconnect();
    },
    showChecked: (() => {
      try { return localStorage.getItem("showChecked") === "1"; } catch { return false; }
    })(),
    toggle() {
      this.showChecked = !this.showChecked;
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

window.addTag = (btn) => {
  const input = document.getElementById("tags");
  const names = input.value.split(",").map((t) => t.trim()).filter(Boolean);
  if (!names.some((n) => n.toLowerCase() === btn.dataset.name.toLowerCase())) names.push(btn.dataset.name);
  input.value = names.join(", ");
};

document.addEventListener("alpine:init", () => {
  // Cook mode: one step at a time, and keep the screen awake while open.
  Alpine.data("cookMode", () => ({
    i: 0,
    count: 0,
    awake: false,
    lock: null,
    async init() {
      this.count = parseInt(this.$el.dataset.count || "0", 10);
      await this.keepAwake();
      this._onVisible = () => document.visibilityState === "visible" && this.keepAwake();
      document.addEventListener("visibilitychange", this._onVisible);
    },
    destroy() {
      document.removeEventListener("visibilitychange", this._onVisible);
      if (this.lock) this.lock.release();
    },
    async keepAwake() {
      try {
        this.lock = await navigator.wakeLock.request("screen");
        this.awake = true;
        this.lock.addEventListener("release", () => (this.awake = false));
      } catch {
        this.awake = false;
      }
    },
    next() {
      if (this.i < this.count - 1) this.i++;
      else window.location.href = window.location.pathname.replace(/\/cook$/, "");
    },
    prev() {
      if (this.i > 0) this.i--;
    },
  }));
});
