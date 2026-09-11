/* Per-field check-off. Field keys and booleans only - never field values -
   so no personal data reaches browser storage. Every read and write is
   guarded: a private window or blocked site data must still render.

   Storage records an explicit boolean per field, never an absence, because
   some rows (the system-verified e-mail) default to checked: deleting a key
   would make a deliberate clear revert on the next load. */
(function () {
  "use strict";

  var root = document.querySelector("[data-checklist]");
  if (!root) { return; }

  var storeKey = "fkc.hub.checks." + root.getAttribute("data-checklist");
  var rows = root.querySelectorAll(".frow[data-field]");
  // Two counters render this number (the pinned bar and the action bar), so
  // collect all of them, not just the first.
  var countEls = document.querySelectorAll("[data-checklist-count]");
  var trackEl = document.querySelector("[data-checklist-track]");

  function load() {
    try { return JSON.parse(localStorage.getItem(storeKey)) || {}; }
    catch (err) { return {}; }
  }

  function save(state) {
    try { localStorage.setItem(storeKey, JSON.stringify(state)); }
    catch (err) { /* storage unavailable - stay in-memory for this page */ }
  }

  function refresh() {
    var done = root.querySelectorAll(".frow[data-field].frow--checked").length;
    countEls.forEach(function (el) {
      el.textContent = done + " / " + rows.length;
    });
    if (trackEl) {
      trackEl.style.width = rows.length
        ? (done / rows.length * 100) + "%"
        : "0%";
    }
  }

  function restore() {
    var state = load();
    rows.forEach(function (row) {
      var stored = state[row.getAttribute("data-field")];
      var on = stored === undefined
        ? row.getAttribute("data-default-checked") === "true"
        : stored === true;
      row.classList.toggle("frow--checked", on);
    });
  }

  rows.forEach(function (row) {
    var button = row.querySelector(".frow__check");
    if (!button) { return; }
    button.addEventListener("click", function () {
      var on = row.classList.toggle("frow--checked");
      var state = load();
      state[row.getAttribute("data-field")] = on;
      save(state);
      refresh();
    });
  });

  var allBtn = document.querySelector("[data-checklist-all]");
  if (allBtn) {
    allBtn.addEventListener("click", function () {
      var state = load();
      rows.forEach(function (row) {
        row.classList.add("frow--checked");
        state[row.getAttribute("data-field")] = true;
      });
      save(state);
      refresh();
    });
  }

  restore();
  refresh();
})();
