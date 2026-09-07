/* Document viewer: tab switching, rotation, zoom. Presentation only -
   nothing here writes to the server or modifies a stored document. */
(function () {
  "use strict";

  var stages = document.querySelectorAll("[data-viewer-stage]");
  var tabs = document.querySelectorAll("[data-viewer-tab]");
  var zoomLabel = document.querySelector("[data-viewer-zoom-label]");
  var state = { deg: 0, scale: 1 };

  function activeDoc() {
    var visible = document.querySelector("[data-viewer-stage]:not([hidden])");
    return visible ? visible.querySelector("[data-viewer-doc]") : null;
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
})();
