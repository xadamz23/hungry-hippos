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
