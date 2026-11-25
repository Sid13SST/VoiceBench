// Progressive enhancement for the dashboard: reveal-on-scroll, count-up numbers, tabs and failure filters.
// Every number is already in the HTML; this only animates it, so the page reads the same without JS.
const root = document.documentElement;
root.classList.add("js");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

function countUp(el) {
  const target = el.dataset.count;
  if (reduce || !target || !/^\d+(\.\d+)?$/.test(target)) return;
  const decimals = (target.split(".")[1] || "").length;
  const end = parseFloat(target);
  const t0 = performance.now();
  const dur = 900;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur);
    const eased = 1 - Math.pow(1 - k, 3);
    el.textContent = (end * eased).toFixed(decimals);
    if (k < 1) requestAnimationFrame(step);
    else el.textContent = target; // always land on the exact stored value
  };
  requestAnimationFrame(step);
}

const io = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    e.target.classList.add("in");
    e.target.querySelectorAll("[data-count]").forEach(countUp);
    io.unobserve(e.target);
  }
}, { rootMargin: "0px 0px -8% 0px" }) : null;

document.querySelectorAll(".reveal").forEach((el) => (io ? io.observe(el) : el.classList.add("in")));

// Tabs: one switch drives every panel with the same data-panel (results and failures).
document.querySelectorAll(".tabs [data-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.tab;
    btn.parentElement.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
    document.querySelectorAll(".tabpanel[data-panel]").forEach((p) => {
      p.hidden = p.dataset.panel !== key;
      if (!p.hidden) p.querySelectorAll(".reveal").forEach((r) => r.classList.add("in"));
    });
  });
});

// Failure explorer filters.
document.querySelectorAll("[data-filter-for]").forEach((bar) => {
  const list = document.getElementById(bar.dataset.filterFor);
  if (!list) return;
  const apply = () => {
    const want = {};
    bar.querySelectorAll("select[data-key]").forEach((s) => (want[s.dataset.key] = s.value));
    list.querySelectorAll(".fail").forEach((card) => {
      card.hidden = (want.lang && card.dataset.lang !== want.lang) || (want.cat && card.dataset.cat !== want.cat);
    });
  };
  bar.addEventListener("change", apply);
});

// Hero playhead travels the width of the waveform.
const wave = document.querySelector(".wave-card .wave");
const head = document.querySelector(".wave-card .playhead");
if (wave && head) {
  const size = () => head.style.setProperty("--w", `${wave.clientWidth}px`);
  size();
  addEventListener("resize", size);
}
