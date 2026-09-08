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
  // Toggling the `hidden` property is enough: hub.css carries a global
  // `[hidden] { display: none !important; }` guard, so it wins over `.vbtn`'s
  // own `display` rule regardless of specificity. No inline style needed.
  function syncQuickLinks() {
    var tab = document.querySelector("[data-viewer-tab].is-active");
    var previewUrl = tab ? tab.getAttribute("data-viewer-preview") : "";
    var downloadUrl = tab ? tab.getAttribute("data-viewer-download") : "";

    if (openLink) {
      if (previewUrl) {
        openLink.href = previewUrl;
        openLink.hidden = false;
      } else {
        openLink.removeAttribute("href");
        openLink.hidden = true;
      }
    }
    if (getLink) {
      if (downloadUrl) {
        getLink.href = downloadUrl;
        getLink.hidden = false;
      } else {
        getLink.removeAttribute("href");
        getLink.hidden = true;
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

  function activeStage() {
    return document.querySelector("[data-viewer-stage]:not([hidden])");
  }

  function fit() {
    // "Ietilpināt" means fit, not 100%. Setting scale = 1 was a no-op at the
    // default zoom, which is why the button appeared dead - and a document
    // turned a quarter turn overflowed, because its bounding box swaps.
    var doc = activeDoc();
    var stage = activeStage();
    if (!doc || !stage) { return; }

    // Measure the untransformed render. The CSS caps both axes at 100%, so
    // this is already the fitted size at 0 degrees.
    var previous = doc.style.transform;
    doc.style.transform = "none";
    var width = doc.clientWidth || doc.offsetWidth;
    var height = doc.clientHeight || doc.offsetHeight;
    doc.style.transform = previous;
    if (!width || !height) { return; }

    var styles = window.getComputedStyle(stage);
    var boxWidth = stage.clientWidth
      - parseFloat(styles.paddingLeft) - parseFloat(styles.paddingRight);
    var boxHeight = stage.clientHeight
      - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom);
    if (boxWidth <= 0 || boxHeight <= 0) { return; }

    // A quarter turn swaps the axes the document needs.
    var quarterTurned = Math.abs(Math.round(state.deg / 90)) % 2 === 1;
    var neededWidth = quarterTurned ? height : width;
    var neededHeight = quarterTurned ? width : height;

    // Rotation is preserved: the button fits what is on screen rather than
    // silently undoing the reviewer's orientation.
    state.scale = Math.min(boxWidth / neededWidth, boxHeight / neededHeight);
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
      fit();
      syncQuickLinks();
    });
  });

  document.querySelectorAll("[data-viewer-rotate]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      state.deg += parseInt(btn.getAttribute("data-viewer-rotate"), 10);
      // Re-fit after turning: the bounding box swaps on a quarter turn, so
      // keeping the old scale would push the document out of the frame.
      fit();
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
  if (resetBtn) { resetBtn.addEventListener("click", fit); }

  function isTextEntry(target) {
    if (!target || !target.tagName) { return false; }
    var tag = target.tagName.toUpperCase();
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
      || target.isContentEditable === true;
  }

  document.addEventListener("keydown", function (event) {
    if (!event.shiftKey) { return; }
    // Shift+Arrow is extend-selection while typing: this page has a rejection
    // textarea, and rotating the document mid-sentence is not a shortcut.
    if (isTextEntry(event.target)) { return; }
    if (event.key === "ArrowLeft") { state.deg -= 90; fit(); }
    if (event.key === "ArrowRight") { state.deg += 90; fit(); }
  });

  // An image has no measurable size until it loads, so the first fit has to
  // wait for it; re-fit on resize because the frame is fluid.
  document.querySelectorAll("[data-viewer-doc]").forEach(function (doc) {
    if (doc.complete) { return; }
    doc.addEventListener("load", fit);
  });
  window.addEventListener("resize", fit);

  apply();
  fit();
  syncQuickLinks();
})();
