/* Document viewer: tab switching, rotation, zoom. Presentation only -
   nothing here writes to the server or modifies a stored document. */
(function () {
  "use strict";

  var stages = document.querySelectorAll("[data-viewer-stage]");
  var tabs = document.querySelectorAll("[data-viewer-tab]");
  var zoomLabel = document.querySelector("[data-viewer-zoom-label]");
  var openLink = document.querySelector("[data-viewer-open]");
  var getLink = document.querySelector("[data-viewer-get]");
  var state = { deg: 0, scale: 1 };

  function activeDoc() {
    var visible = document.querySelector("[data-viewer-stage]:not([hidden])");
    return visible ? visible.querySelector("[data-viewer-doc]") : null;
  }

  // Points the "Jaunā cilnē" / "Lejupielādēt" toolbar links at whichever tab
  // is active. Both links carry no href in the markup (only `hidden`), so a
  // document that fails to load here never leaves a stale link pointing at a
  // different (or no longer relevant) document - each call rebuilds both
  // from scratch off the active tab's own data attributes.
  //
  // Both the `hidden` property (kept for semantics/assistive tech) and an
  // explicit inline `style.display` are set together: `.vbtn` declares its
  // own `display: inline-flex`, and a plain author stylesheet rule always
  // outranks the user-agent `[hidden] { display: none }` rule regardless of
  // selector specificity - so `hidden` alone would not actually hide these
  // particular elements. The inline style (highest-precedence, short of
  // `!important`) is what does the actual hiding.
  function syncQuickLinks() {
    var tab = document.querySelector("[data-viewer-tab].is-active");
    var previewUrl = tab ? tab.getAttribute("data-viewer-preview") : "";
    var downloadUrl = tab ? tab.getAttribute("data-viewer-download") : "";

    if (openLink) {
      if (previewUrl) {
        openLink.href = previewUrl;
        openLink.hidden = false;
        openLink.style.display = "";
      } else {
        openLink.removeAttribute("href");
        openLink.hidden = true;
        openLink.style.display = "none";
      }
    }
    if (getLink) {
      if (downloadUrl) {
        getLink.href = downloadUrl;
        getLink.hidden = false;
        getLink.style.display = "";
      } else {
        getLink.removeAttribute("href");
        getLink.hidden = true;
        getLink.style.display = "none";
      }
    }
  }

  function apply() {
    var doc = activeDoc();
    if (doc) {
      doc.style.transform =
        "rotate(" + state.deg + "deg) scale(" + state.scale + ")";
    }
    if (zoomLabel) {
      zoomLabel.textContent = Math.round(state.scale * 100) + " %";
    }
  }

  function reset() {
    state.deg = 0;
    state.scale = 1;
    apply();
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      var index = tab.getAttribute("data-viewer-tab");
      tabs.forEach(function (t) { t.classList.remove("is-active"); });
      tab.classList.add("is-active");
      stages.forEach(function (stage) {
        stage.hidden = stage.getAttribute("data-viewer-stage") !== index;
      });
      reset();
      syncQuickLinks();
    });
  });

  document.querySelectorAll("[data-viewer-rotate]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      state.deg += parseInt(btn.getAttribute("data-viewer-rotate"), 10);
      apply();
    });
  });

  document.querySelectorAll("[data-viewer-zoom]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var delta = parseFloat(btn.getAttribute("data-viewer-zoom"));
      state.scale = Math.min(3, Math.max(0.3, state.scale + delta));
      apply();
    });
  });

  var resetBtn = document.querySelector("[data-viewer-reset]");
  if (resetBtn) { resetBtn.addEventListener("click", reset); }

  document.addEventListener("keydown", function (event) {
    if (!event.shiftKey) { return; }
    if (event.key === "ArrowLeft") { state.deg -= 90; apply(); }
    if (event.key === "ArrowRight") { state.deg += 90; apply(); }
  });

  apply();
  syncQuickLinks();
})();
