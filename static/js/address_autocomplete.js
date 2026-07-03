/**
 * Assist-only address autocomplete for the parent registration form.
 *
 * - Works on [data-address-autocomplete="1"] inputs.
 * - No VZD codes are persisted; the selected text is copied into the plain
 *   text field only.
 * - Falls back to manual entry if the endpoint is unreachable or returns no data.
 */
(function () {
  "use strict";

  var DEBOUNCE_MS = 200;
  var MIN_CHARS = 3;

  var MSG_START = "Sāciet rakstīt adresi…";
  var MSG_KEEP_TYPING = "Turpiniet rakstīt…";
  var MSG_NOT_FOUND = "Adreses nav atrastas";
  var MSG_ERROR = "Neizdevās ielādēt adreses. Varat ievadīt manuāli.";

  function debounce(fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      var self = this;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(self, args);
      }, ms);
    };
  }

  function createDropdown(input) {
    var existing = input.parentNode.querySelector(".fk-address-dropdown");
    if (existing) return existing;
    var dropdown = document.createElement("ul");
    dropdown.className = "fk-address-dropdown";
    dropdown.setAttribute("role", "listbox");
    input.parentNode.style.position = "relative";
    input.parentNode.appendChild(dropdown);
    return dropdown;
  }

  function closeDropdown(dropdown) {
    if (!dropdown) return;
    dropdown.innerHTML = "";
    dropdown.style.display = "none";
  }

  function showMessage(dropdown, message) {
    dropdown.innerHTML = "";
    dropdown.style.display = "block";
    var li = document.createElement("li");
    li.className = "fk-address-dropdown__message";
    li.textContent = message;
    dropdown.appendChild(li);
  }

  function renderResults(input, dropdown, results) {
    dropdown.innerHTML = "";
    if (!results.length) {
      showMessage(dropdown, MSG_NOT_FOUND);
      return;
    }
    dropdown.style.display = "block";
    results.forEach(function (result) {
      var li = document.createElement("li");
      li.className = "fk-address-dropdown__item";
      li.setAttribute("role", "option");
      li.setAttribute("data-kind", result.kind);
      li.setAttribute("data-id", result.id);
      li.setAttribute("data-label", result.label);
      var label = document.createElement("span");
      label.className = "fk-address-dropdown__label";
      label.textContent = result.label;
      var hint = document.createElement("span");
      hint.className = "fk-address-dropdown__hint";
      hint.textContent = result.hint;
      li.appendChild(label);
      li.appendChild(hint);
      li.addEventListener("mousedown", function (event) {
        event.preventDefault();
        selectResult(input, dropdown, result);
      });
      dropdown.appendChild(li);
    });
  }

  function selectResult(input, dropdown, result) {
    input.value = result.label;
    if (result.kind === "group") {
      input.setAttribute("data-address-group-id", result.id);
      input.setAttribute("data-address-group-label", result.label);
      input.removeAttribute("data-address-building-id");
      input.removeAttribute("data-address-building-label");
      input.focus();
      // Keep dropdown open and fetch building addresses under this group.
      dropdown.innerHTML = "";
      dropdown.style.display = "block";
      fetchSuggestions(input, dropdown);
    } else if (result.kind === "address") {
      input.setAttribute("data-address-building-id", result.id);
      input.setAttribute("data-address-building-label", result.label);
      input.removeAttribute("data-address-group-id");
      input.removeAttribute("data-address-group-label");
      input.focus();
      // Keep dropdown open and fetch apartment suggestions under this building.
      dropdown.innerHTML = "";
      dropdown.style.display = "block";
      fetchSuggestions(input, dropdown);
    } else if (result.kind === "apartment") {
      input.removeAttribute("data-address-group-id");
      input.removeAttribute("data-address-group-label");
      input.removeAttribute("data-address-building-id");
      input.removeAttribute("data-address-building-label");
      closeDropdown(dropdown);
    } else {
      input.removeAttribute("data-address-group-id");
      input.removeAttribute("data-address-group-label");
      input.removeAttribute("data-address-building-id");
      input.removeAttribute("data-address-building-label");
      closeDropdown(dropdown);
    }
  }

  function getGroupId(input) {
    var raw = input.getAttribute("data-address-group-id");
    if (!raw) return null;
    var value = input.value.trim();
    var groupLabel = input.getAttribute("data-address-group-label") || "";
    // Clear the active group if the user has deleted or altered the group text.
    if (groupLabel && value.indexOf(groupLabel) !== 0) {
      input.removeAttribute("data-address-group-id");
      input.removeAttribute("data-address-group-label");
      return null;
    }
    return raw;
  }

  function getBuildingId(input) {
    var raw = input.getAttribute("data-address-building-id");
    if (!raw) return null;
    var value = input.value.trim();
    var buildingLabel = input.getAttribute("data-address-building-label") || "";
    // Clear the active building if the user has deleted or altered the building text.
    if (buildingLabel && value.indexOf(buildingLabel) !== 0) {
      input.removeAttribute("data-address-building-id");
      input.removeAttribute("data-address-building-label");
      return null;
    }
    return raw;
  }

  function getQuery(input) {
    var value = input.value.trim();
    var groupLabel = input.getAttribute("data-address-group-label") || "";
    if (getGroupId(input) && groupLabel && value.indexOf(groupLabel) === 0) {
      var suffix = value.slice(groupLabel.length).replace(/^\s*,?\s*/, "").trim();
      return suffix || groupLabel;
    }
    var buildingLabel = input.getAttribute("data-address-building-label") || "";
    if (getBuildingId(input) && buildingLabel && value.indexOf(buildingLabel) === 0) {
      var buildingSuffix = value.slice(buildingLabel.length).replace(/^\s*,?\s*/, "").trim();
      return buildingSuffix || buildingLabel;
    }
    return value;
  }

  function fetchSuggestions(input, dropdown) {
    var groupId = getGroupId(input);
    var buildingId = getBuildingId(input);
    var query = getQuery(input);
    if (!query) {
      showMessage(dropdown, MSG_START);
      return;
    }
    if (query.length < MIN_CHARS && !groupId && !buildingId) {
      showMessage(dropdown, MSG_KEEP_TYPING);
      return;
    }

    var url = "/addresses/autocomplete/?q=" + encodeURIComponent(query);
    if (buildingId) {
      url += "&building=" + encodeURIComponent(buildingId);
    } else if (groupId) {
      url += "&group=" + encodeURIComponent(groupId);
    }

    if (input._addressAutocompleteController) {
      input._addressAutocompleteController.abort();
    }
    input._addressAutocompleteController = new AbortController();

    fetch(url, { signal: input._addressAutocompleteController.signal })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        renderResults(input, dropdown, data.results || []);
      })
      .catch(function (error) {
        if (error.name === "AbortError") return;
        showMessage(dropdown, MSG_ERROR);
      });
  }

  function initInput(input) {
    if (input._addressAutocompleteBound) return;
    input._addressAutocompleteBound = true;

    var dropdown = createDropdown(input);
    var debouncedFetch = debounce(function () {
      fetchSuggestions(input, dropdown);
    }, DEBOUNCE_MS);

    input.addEventListener("focus", function () {
      if (input.value.trim().length < MIN_CHARS) {
        showMessage(dropdown, input.value.trim() ? MSG_KEEP_TYPING : MSG_START);
      } else {
        debouncedFetch();
      }
    });

    input.addEventListener("input", function () {
      debouncedFetch();
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeDropdown(dropdown);
        return;
      }
      var active = dropdown.querySelector(".fk-address-dropdown__item--active");
      if (event.key === "ArrowDown") {
        event.preventDefault();
        var items = dropdown.querySelectorAll(".fk-address-dropdown__item");
        if (!items.length) return;
        if (active) {
          active.classList.remove("fk-address-dropdown__item--active");
          var next = active.nextElementSibling;
          if (next && next.classList.contains("fk-address-dropdown__item")) {
            next.classList.add("fk-address-dropdown__item--active");
          } else {
            items[0].classList.add("fk-address-dropdown__item--active");
          }
        } else {
          items[0].classList.add("fk-address-dropdown__item--active");
        }
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        var items = dropdown.querySelectorAll(".fk-address-dropdown__item");
        if (!items.length) return;
        if (active) {
          active.classList.remove("fk-address-dropdown__item--active");
          var prev = active.previousElementSibling;
          if (prev && prev.classList.contains("fk-address-dropdown__item")) {
            prev.classList.add("fk-address-dropdown__item--active");
          } else {
            items[items.length - 1].classList.add("fk-address-dropdown__item--active");
          }
        } else {
          items[items.length - 1].classList.add("fk-address-dropdown__item--active");
        }
      } else if (event.key === "Enter") {
        if (active) {
          event.preventDefault();
          active.dispatchEvent(new Event("mousedown"));
        }
      }
    });

    document.addEventListener("click", function (event) {
      if (!input.contains(event.target) && !dropdown.contains(event.target)) {
        closeDropdown(dropdown);
      }
    });
  }

  function init() {
    document.querySelectorAll("[data-address-autocomplete='1']").forEach(initInput);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
