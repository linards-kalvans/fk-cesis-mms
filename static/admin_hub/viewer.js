/* Document viewer: tab switching, rotation, zoom. Presentation only -
   nothing here writes to the server or modifies a stored document.

   Safe native previews: only loaded raster images may be transformed or
   zoomed. PDF/unknown/missing panels and images that failed to load keep the
   controls disabled and show no zoom percentage. */
(function () {
  "use strict";

  var stages = document.querySelectorAll("[data-viewer-stage]");
  var tabs = document.querySelectorAll("[data-viewer-tab]");
  var zoomLabel = document.querySelector("[data-viewer-zoom-label]");
  var openLink = document.querySelector("[data-viewer-open]");
  var getLink = document.querySelector("[data-viewer-get]");
  var controls = [];
  var failedImages = typeof WeakSet === "function" ? new WeakSet() : null;
  var state = { deg: 0, scale: 1 };

  ["[data-viewer-rotate]", "[data-viewer-zoom]", "[data-viewer-reset]"].forEach(
    function (selector) {
      document.querySelectorAll(selector).forEach(function (element) {
        controls.push(element);
      });
    }
  );

  function activeStage() {
    return document.querySelector("[data-viewer-stage]:not([hidden])");
  }

  function imageForStage(stage) {
    return stage ? stage.querySelector("[data-viewer-doc]") : null;
  }

  function isUsableImage(image) {
    if (!image) { return false; }
    if (failedImages && failedImages.has(image)) { return false; }
    return image.complete === true
      && (image.naturalWidth || 0) > 0
      && (image.naturalHeight || 0) > 0;
  }

  function activeImage() {
    var image = imageForStage(activeStage());
    return isUsableImage(image) ? image : null;
  }

  function setControlsEnabled(enabled) {
    controls.forEach(function (control) {
      control.disabled = !enabled;
    });
    if (!enabled && zoomLabel) {
      zoomLabel.textContent = "—";
    }
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
    var image = activeImage();
    if (!image) { return; }
    image.style.transform =
      "rotate(" + state.deg + "deg) scale(" + state.scale + ")";
    if (zoomLabel) {
      zoomLabel.textContent = Math.round(state.scale * 100) + " %";
    }
  }

  function fit() {
    // "Ietilpināt" means fit, not 100%: setting scale = 1 was a no-op at the
    // default zoom, which is why the button appeared dead.
    var image = activeImage();
    var stage = activeStage();
    if (!image || !stage) { return; }

    var styles = window.getComputedStyle(stage);
    var boxWidth = stage.clientWidth
      - parseFloat(styles.paddingLeft) - parseFloat(styles.paddingRight);
    var boxHeight = stage.clientHeight
      - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom);
    if (!(boxWidth > 0) || !(boxHeight > 0)) { return; }

    // Measure the picture, not the element box. With object-fit: contain the
    // box is the stage and the picture is letterboxed inside it, so reading
    // clientWidth/Height would overstate the height of a portrait photo and
    // under-scale it after a rotation. naturalWidth/Height are the true
    // pixels; they are 0 until the image has loaded, hence the guard.
    var naturalWidth = image.naturalWidth || 0;
    var naturalHeight = image.naturalHeight || 0;
    if (!naturalWidth || !naturalHeight) { return; }

    // How large the picture renders at scale 1, after the CSS caps letterbox
    // it into the stage.
    var containScale = Math.min(
      1, Math.min(boxWidth / naturalWidth, boxHeight / naturalHeight)
    );
    var pictureWidth = naturalWidth * containScale;
    var pictureHeight = naturalHeight * containScale;

    // A quarter turn swaps which axis the picture needs.
    var quarterTurned = Math.abs(Math.round(state.deg / 90)) % 2 === 1;
    var neededWidth = quarterTurned ? pictureHeight : pictureWidth;
    var neededHeight = quarterTurned ? pictureWidth : pictureHeight;
    if (!(neededWidth > 0) || !(neededHeight > 0)) { return; }

    // Rotation is preserved: the button fits what is on screen rather than
    // silently undoing the reviewer's chosen orientation.
    state.scale = Math.min(boxWidth / neededWidth, boxHeight / neededHeight);
    apply();
  }

  // Applies the enabled/disabled state for the panel that is on screen. When a
  // usable image is active it also re-applies the current transform and fits
  // it; every other format leaves the toolbar inert with an unavailable
  // readout.
  function refreshControls() {
    var image = activeImage();
    setControlsEnabled(Boolean(image));
    if (!image) { return; }
    apply();
    fit();
  }

  function activateTab(tab, resetTransform) {
    var index = tab.getAttribute("data-viewer-tab");
    tabs.forEach(function (item) { item.classList.remove("is-active"); });
    tab.classList.add("is-active");
    stages.forEach(function (stage) {
      stage.hidden = stage.getAttribute("data-viewer-stage") !== index;
    });
    // Each tab starts from a neutral orientation and zoom; transform state is
    // never carried across document switches.
    if (resetTransform) {
      state = { deg: 0, scale: 1 };
    }
    syncQuickLinks();
    refreshControls();
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      if (tab.disabled) { return; }
      activateTab(tab, true);
    });
  });

  controls.forEach(function (control) {
    var rotate = control.getAttribute("data-viewer-rotate");
    var zoom = control.getAttribute("data-viewer-zoom");
    if (rotate !== null) {
      control.addEventListener("click", function () {
        if (!activeImage()) { return; }
        state.deg += parseInt(rotate, 10);
        // Re-fit after turning: the bounding box swaps on a quarter turn, so
        // keeping the old scale would push the document out of the frame.
        fit();
      });
    } else if (zoom !== null) {
      control.addEventListener("click", function () {
        if (!activeImage()) { return; }
        state.scale = Math.min(3, Math.max(0.3, state.scale + parseFloat(zoom)));
        apply();
      });
    } else if (control.hasAttribute("data-viewer-reset")) {
      control.addEventListener("click", function () {
        if (!activeImage()) { return; }
        // Fit preserves the reviewer's chosen orientation, matching the fit()
        // contract above; reset recalculates only the zoom.
        fit();
      });
    }
  });

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
    // Only a successfully loaded, visible raster image can be rotated. Never
    // mutate a hidden image while a PDF/unknown panel is active.
    if (!activeImage()) { return; }
    if (event.key === "ArrowLeft") { state.deg -= 90; fit(); }
    if (event.key === "ArrowRight") { state.deg += 90; fit(); }
  });

  // Attach per-image load/error handling: an image has no measurable size
  // until it loads, and a failed image (for example HEIC in an unsupported
  // browser) reveals the escaped fallback while keeping transforms disabled.
  stages.forEach(function (stage) {
    var image = imageForStage(stage);
    if (!image) { return; }
    var fallback = stage.querySelector("[data-viewer-image-error]");

    function clearError() {
      if (failedImages) { failedImages.delete(image); }
      image.hidden = false;
      if (fallback) { fallback.hidden = true; }
    }

    function showError() {
      if (failedImages) { failedImages.add(image); }
      image.hidden = true;
      if (fallback) { fallback.hidden = false; }
    }

    image.addEventListener("load", function () {
      clearError();
      if (activeImage() === image) { refreshControls(); }
    });
    image.addEventListener("error", function () {
      showError();
      if (imageForStage(activeStage()) === image) { refreshControls(); }
    });

    // The load/error event may already have fired before this script ran.
    if (image.complete && !((image.naturalWidth || 0) > 0)) {
      showError();
    }
  });

  // Re-fit on resize because the frame is fluid.
  window.addEventListener("resize", function () {
    if (activeImage()) { fit(); }
  });

  var initialTab = document.querySelector("[data-viewer-tab].is-active");
  if (initialTab && initialTab.disabled) {
    initialTab = null;
  }
  if (!initialTab) {
    // Fallback for markup without an explicit initial selection: the first
    // available tab wins, and an all-missing viewer stays without any active
    // tab or stale toolbar links.
    tabs.forEach(function (tab) {
      if (!initialTab && !tab.disabled) { initialTab = tab; }
    });
  }

  if (initialTab) {
    activateTab(initialTab, true);
  } else {
    setControlsEnabled(false);
    syncQuickLinks();
  }
})();
