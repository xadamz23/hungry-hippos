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
      const m = this.amt.match(/^(\d+(?:\.\d+)?)(.*)$/);
      if (m) {
        const n = Math.max(0, parseFloat(m[1]) + delta);
        this.amt = (n % 1 ? n.toFixed(1) : String(n)) + m[2];
      } else if (!this.amt.trim() && delta > 0) {
        this.amt = "1";
      }
    },
  }));

  // List: checked items are hidden by default; the choice is remembered on this device.
  Alpine.data("listView", () => ({
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

  // List quick-add: typing opens a dropdown of matching staples. The last word typed is matched against the
  // start of each word in a staple's name, skipping amounts, so "2 gal mi" still finds Milk. Arrow keys move
  // through the matches and Enter adds the highlighted one; with nothing highlighted Enter adds the typed text.
  Alpine.data("quickAdd", () => ({
    q: "",
    open: false,
    active: -1,
    limit: 6,
    init() {
      this.$watch("q", () => (this.active = -1));
    },
    word() {
      const words = this.q.toLowerCase().split(/\s+/).filter((w) => w && !/^[\d.\/½¼¾⅓⅔-]+$/.test(w));
      return words.at(-1) || "";
    },
    matches(name) {
      const w = this.word();
      return !!w && name.toLowerCase().split(/\s+/).some((part) => part.startsWith(w));
    },
    // Names of the staples to show, best first (server order), capped at `limit`.
    hits() {
      const names = [...this.$root.querySelectorAll("#add-suggest [data-name]")].map((b) => b.dataset.name);
      return names.filter((n) => this.matches(n)).slice(0, this.limit);
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
    pick(e) {
      const el = this.isOpen() && this.options()[this.active];
      if (!el) return;
      e.preventDefault();
      el.click();
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
