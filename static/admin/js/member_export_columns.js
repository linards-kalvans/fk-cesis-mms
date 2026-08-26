(function () {
  "use strict";

  /**
   * Member-export template column picker.
   *
   * Maintains two <ul>s: selected + available. The hidden JSON input is the
   * source of truth at submit time. Every add/remove/up/down mutates that
   * hidden input. Uses textContent for new label DOM nodes (never raw HTML)
   * to keep user-controlled values out of innerHTML.
   */

  function bootstrap(root) {
    if (root.dataset.memberExportColumnsReady === "true") {
      return;
    }
    root.dataset.memberExportColumnsReady = "true";

    var selectedList = root.querySelector("[data-selected-list]");
    var availableList = root.querySelector("[data-available-list]");
    var hiddenInput = root.querySelector("[data-member-export-columns-input]");
    if (!selectedList || !availableList || !hiddenInput) {
      return;
    }

    var registry = {};
    var labels = {};
    root.querySelectorAll("[data-available-list] [data-key]").forEach(function (li) {
      registry[li.dataset.key] = li;
      var labelEl = li.querySelector(".fk-member-export-columns__label");
      labels[li.dataset.key] = labelEl ? labelEl.textContent : li.dataset.key;
    });
    root.querySelectorAll("[data-selected-list] [data-key]").forEach(function (li) {
      var labelEl = li.querySelector(".fk-member-export-columns__label");
      if (!labels[li.dataset.key]) {
        labels[li.dataset.key] = labelEl ? labelEl.textContent : li.dataset.key;
      }
    });

    function readSelected() {
      try {
        var parsed = JSON.parse(hiddenInput.value || "[]");
        if (Array.isArray(parsed)) {
          return parsed.filter(function (k) { return typeof k === "string"; });
        }
      } catch (e) {
        // ignore — fall through to empty
      }
      return [];
    }

    function writeSelected(keys) {
      hiddenInput.value = JSON.stringify(keys);
    }

    function moveKey(keys, key, delta) {
      var idx = keys.indexOf(key);
      if (idx === -1) {
        return keys;
      }
      var nextIdx = idx + delta;
      if (nextIdx < 0 || nextIdx >= keys.length) {
        return keys;
      }
      var swapped = keys.slice();
      var tmp = swapped[idx];
      swapped[idx] = swapped[nextIdx];
      swapped[nextIdx] = tmp;
      return swapped;
    }

    function buildSelectedItem(key) {
      var li = document.createElement("li");
      li.className = "fk-member-export-columns__item";
      li.dataset.key = key;

      var label = document.createElement("span");
      label.className = "fk-member-export-columns__label";
      label.textContent = labels[key] || key;

      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "fk-column-remove";
      removeBtn.dataset.action = "remove";
      removeBtn.dataset.key = key;
      removeBtn.setAttribute("aria-label", "Noņemt kolonnu " + (labels[key] || key));
      removeBtn.textContent = "−";

      var upBtn = document.createElement("button");
      upBtn.type = "button";
      upBtn.className = "fk-column-move-up";
      upBtn.dataset.action = "up";
      upBtn.dataset.key = key;
      upBtn.setAttribute("aria-label", "Pārvietot augšup");
      upBtn.textContent = "↑";

      var downBtn = document.createElement("button");
      downBtn.type = "button";
      downBtn.className = "fk-column-move-down";
      downBtn.dataset.action = "down";
      downBtn.dataset.key = key;
      downBtn.setAttribute("aria-label", "Pārvietot lejup");
      downBtn.textContent = "↓";

      li.appendChild(label);
      li.appendChild(removeBtn);
      li.appendChild(upBtn);
      li.appendChild(downBtn);
      return li;
    }

    function syncAvailable(keys) {
      var selectedSet = {};
      keys.forEach(function (k) { selectedSet[k] = true; });
      Object.keys(registry).forEach(function (key) {
        var availableLi = registry[key];
        if (!availableLi) {
          return;
        }
        if (selectedSet[key]) {
          if (availableLi.parentNode) {
            availableLi.parentNode.removeChild(availableLi);
          }
        } else if (!availableLi.parentNode) {
          availableList.appendChild(availableLi);
        }
      });
    }

    function renderSelected(keys) {
      // Remove all existing selected list items, then add fresh ones in order.
      while (selectedList.firstChild) {
        selectedList.removeChild(selectedList.firstChild);
      }
      keys.forEach(function (key) {
        if (registry[key] === undefined && labels[key] === undefined) {
          return;
        }
        selectedList.appendChild(buildSelectedItem(key));
      });
    }

    function refresh() {
      var keys = readSelected();
      renderSelected(keys);
      syncAvailable(keys);
    }

    root.addEventListener("click", function (event) {
      var target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      var action = target.dataset.action;
      if (!action) {
        return;
      }
      var key = target.dataset.key;
      if (!key) {
        return;
      }
      var keys = readSelected();
      if (action === "add") {
        if (keys.indexOf(key) === -1) {
          keys.push(key);
        }
      } else if (action === "remove") {
        keys = keys.filter(function (k) { return k !== key; });
      } else if (action === "up") {
        keys = moveKey(keys, key, -1);
      } else if (action === "down") {
        keys = moveKey(keys, key, 1);
      }
      writeSelected(keys);
      refresh();
      event.preventDefault();
    });
  }

  function init() {
    document
      .querySelectorAll("[data-member-export-columns]")
      .forEach(bootstrap);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
