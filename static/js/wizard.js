(function () {
  'use strict';

  var steps = document.querySelectorAll('.fk-wizard-step');
  if (!steps.length) return;

  var indicators = document.querySelectorAll('.fk-stepper .fk-step');
  var mobileCount = document.querySelector('.fk-mobile-step-count');
  var mobileLabel = document.querySelector('.fk-mobile-step-label');
  var progressLine = document.querySelector('.fk-progress-line span');
  var form = document.querySelector('.fk-workspace-form');
  var nextButtons = document.querySelectorAll('[data-wizard-next]');

  var current = 0;
  var total = steps.length;

  // ---- Step name resolution -------------------------------------------------
  // The wizard template assigns each `.fk-wizard-step` container a numeric
  // `data-step` (step index). The semantic "step name" (documents/guardian/
  // member/agreement) is the `data-step-required` value of the inputs inside
  // that step. We derive a step-index → step-name map by sniffing the first
  // `[data-step-required]` input inside each step container. Containers
  // without any `[data-step-required]` (e.g. the review step) get null.
  var stepNames = [];
  steps.forEach(function (stepEl) {
    var anyRequired = stepEl.querySelector('[data-step-required]');
    stepNames.push(anyRequired ? anyRequired.getAttribute('data-step-required') : null);
  });

  // Personal-id format regex.
  var pidPattern = /^\d{6}-\d{5}$/;

  // ---- Step-gating validation -----------------------------------------------
  // Returns true when all `[data-step-required]` inputs in step `n` are filled
  // (and format-valid where applicable). Renders inline errors as a sibling
  // <p class="fk-form-error" data-step-error>. The conditional waiver for
  // `member_actual_address` mirrors the server-side rule in forms.py::clean().

  function getStepName(n) {
    return stepNames[n];
  }

  function isFileFieldFilled(input) {
    if (input.files && input.files.length > 0) return true;
    // Already-uploaded detection: form_field.html renders an
    // `fk-dropzone--filled` label around an existing document. We use that
    // class as the DOM signal — there's no separate hidden marker emitted
    // for persisted uploads. Falls back to a generic [data-uploaded-document]
    // hook in case the partial is restructured later.
    var dropzone = input.closest('.fk-dropzone');
    if (dropzone && dropzone.classList.contains('fk-dropzone--filled')) return true;
    if (input.closest('.fk-form-field')) {
      var marker = input.closest('.fk-form-field').querySelector('[data-uploaded-document]');
      if (marker) return true;
    }
    return false;
  }

  function isInputFilled(input) {
    if (input.type === 'file') return isFileFieldFilled(input);
    if (input.type === 'checkbox') return input.checked;
    return (input.value || '').trim() !== '';
  }

  function getOrCreateErrorEl(input) {
    var container = input.closest('.fk-form-field')
      || input.closest('.fk-consent')
      || input.parentNode;
    if (!container) return null;
    var existing = container.querySelector('[data-step-error]');
    if (existing) return existing;
    var p = document.createElement('p');
    p.className = 'fk-form-error';
    p.setAttribute('data-step-error', '');
    p.hidden = true;
    container.appendChild(p);
    return p;
  }

  function clearError(input) {
    var errEl = input.parentNode
      ? (input.closest('.fk-form-field') || input.closest('.fk-consent') || input.parentNode).querySelector('[data-step-error]')
      : null;
    if (errEl) {
      errEl.hidden = true;
      errEl.textContent = '';
    }
    input.classList.remove('fk-input--error');
    input.removeAttribute('data-step-invalid');
  }

  function showError(input, message) {
    var errEl = getOrCreateErrorEl(input);
    if (errEl) {
      errEl.textContent = message || '';
      errEl.hidden = !message;
    }
    input.classList.add('fk-input--error');
    input.setAttribute('data-step-invalid', '1');
  }

  function shouldSkipMemberActualAddress(input) {
    if (input.name !== 'member_actual_address') return false;
    var cb = document.getElementById('id_member_same_address_as_guardian');
    return !!(cb && cb.checked);
  }

  function validateField(input, renderErrors) {
    // Returns true when the field passes its step-gating check. When
    // `renderErrors` is true, inline error markup is updated; otherwise the
    // function is a pure predicate (used for the gating boolean on every
    // keystroke without flicker).
    if (shouldSkipMemberActualAddress(input)) {
      if (renderErrors) clearError(input);
      return true;
    }

    var filled = isInputFilled(input);
    if (!filled) {
      if (renderErrors) {
        var emptyMsg = input.getAttribute('data-step-error-empty') || '';
        showError(input, emptyMsg);
      }
      return false;
    }

    // Format check (currently only personal-id inputs carry data-step-error-format).
    var formatMsg = input.getAttribute('data-step-error-format');
    if (formatMsg && input.type !== 'checkbox' && input.type !== 'file') {
      var value = (input.value || '').trim();
      if (!pidPattern.test(value)) {
        if (renderErrors) showError(input, formatMsg);
        return false;
      }
    }

    if (renderErrors) clearError(input);
    return true;
  }

  function stepInputs(n) {
    var stepEl = steps[n];
    if (!stepEl) return [];
    var stepName = getStepName(n);
    if (!stepName) return [];
    return Array.prototype.slice.call(
      stepEl.querySelectorAll('[data-step-required="' + stepName + '"]')
    );
  }

  function validateStep(n) {
    var inputs = stepInputs(n);
    if (!inputs.length) return true;
    var ok = true;
    inputs.forEach(function (input) {
      if (!validateField(input, false)) ok = false;
    });
    return ok;
  }

  function refreshNextDisabled() {
    var ok = validateStep(current);
    nextButtons.forEach(function (btn) {
      btn.disabled = !ok;
    });
  }

  // ---- Step transitions -----------------------------------------------------
  function showStep(n) {
    // Flush any pending auto-save before changing steps so a partially-typed
    // field is durable across navigations.
    flushAutoSave();

    steps.forEach(function (s, i) {
      s.classList.toggle('fk-wizard-step--active', i === n);
    });
    indicators.forEach(function (s, i) {
      s.classList.toggle('fk-step--active', i === n);
    });
    if (mobileCount) mobileCount.textContent = (n + 1) + ' / ' + total;
    if (mobileLabel && indicators[n]) {
      var lbl = indicators[n].querySelector('.fk-step-label');
      if (lbl) mobileLabel.textContent = lbl.textContent;
    }
    if (progressLine) {
      progressLine.style.width = Math.round((n + 1) / total * 100) + '%';
    }
    current = n;
    if (n === total - 1) updateReview();
    refreshNextDisabled();
    window.scrollTo(0, 0);
  }

  function updateReview() {
    document.querySelectorAll('[data-review-for]').forEach(function (el) {
      var id = el.getAttribute('data-review-for');
      var input = document.getElementById(id);
      if (!input) return;
      if (input.type === 'file') return;
      var val;
      if (input.type === 'checkbox') {
        val = input.checked ? 'Jā' : 'Nē';
      } else if (input.tagName === 'SELECT') {
        var opt = input.options[input.selectedIndex];
        val = (opt && opt.text) ? opt.text : '—';
      } else {
        val = input.value || '—';
      }
      el.textContent = val;
    });
  }

  // ---- Auto-save controller -------------------------------------------------
  var DEBOUNCE_MS = 500;
  var RETRY_DELAY_MS = 2000;

  var saveIndicator = document.querySelector('[data-save-indicator]');
  var saveLabel = saveIndicator
    ? saveIndicator.querySelector('[data-save-label]')
    : null;

  function getSaveMessage(state) {
    if (!saveIndicator) return '';
    return saveIndicator.getAttribute('data-save-message-' + state) || '';
  }

  function setSaveState(state) {
    if (!saveIndicator) return;
    saveIndicator.setAttribute('data-save-state', state);
    if (state === 'idle') {
      saveIndicator.hidden = true;
      if (saveLabel) saveLabel.textContent = '';
      return;
    }
    saveIndicator.hidden = false;
    if (saveLabel) saveLabel.textContent = getSaveMessage(state);
  }

  function getCsrfToken() {
    if (!form) return '';
    var input = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  function buildAutoSavePayload() {
    if (!form) return null;
    var fd = new FormData();
    // Serialize every non-file input. File uploads are owned by
    // async_upload.js; auto-save persists everything else.
    var elements = form.querySelectorAll('input, select, textarea');
    elements.forEach(function (el) {
      if (!el.name) return;
      if (el.disabled) return;
      if (el.type === 'file') return;
      if (el.type === 'submit' || el.type === 'button') return;
      if ((el.type === 'checkbox' || el.type === 'radio') && !el.checked) return;
      fd.append(el.name, el.value);
    });
    return fd;
  }

  var autoSaveTimer = null;
  var autoSaveInFlight = false;

  function postAutoSave(isRetry) {
    if (!form) return Promise.resolve();
    // Silently skip if a previous save is still in flight; the in-flight POST
    // serializes the live FormData at send time, so the latest field values
    // are captured regardless of which call wins.
    if (autoSaveInFlight) return Promise.resolve();
    var payload = buildAutoSavePayload();
    if (!payload) return Promise.resolve();
    setSaveState('saving');
    autoSaveInFlight = true;
    return fetch(form.action || window.location.pathname, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': getCsrfToken(),
        'Accept': 'application/json'
      },
      body: payload
    }).then(function (resp) {
      if (resp.status === 200) {
        return resp.json().then(function (_data) {
          autoSaveInFlight = false;
          setSaveState('saved');
        }).catch(function () {
          // Body wasn't JSON but server returned 200 — still treat as saved.
          autoSaveInFlight = false;
          setSaveState('saved');
        });
      }
      // Any non-200 (400, 404, 5xx) is treated uniformly: retry once then error.
      autoSaveInFlight = false;
      if (!isRetry) {
        return new Promise(function (resolve) {
          setTimeout(function () {
            resolve(postAutoSave(true));
          }, RETRY_DELAY_MS);
        });
      }
      setSaveState('error');
    }).catch(function () {
      autoSaveInFlight = false;
      if (!isRetry) {
        return new Promise(function (resolve) {
          setTimeout(function () {
            resolve(postAutoSave(true));
          }, RETRY_DELAY_MS);
        });
      }
      setSaveState('error');
    });
  }

  function scheduleAutoSave() {
    if (autoSaveTimer) clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(function () {
      autoSaveTimer = null;
      postAutoSave(false);
    }, DEBOUNCE_MS);
  }

  function flushAutoSave() {
    if (autoSaveTimer) {
      clearTimeout(autoSaveTimer);
      autoSaveTimer = null;
    }
    // Fire immediately without waiting for the debounce window.
    postAutoSave(false);
  }

  // ---- Event wiring ---------------------------------------------------------
  // Step-gating: blur on every required input the first time, change/input on
  // any input that has previously been shown invalid.
  function bindStepGating() {
    var allRequired = document.querySelectorAll('[data-step-required]');
    allRequired.forEach(function (input) {
      input.addEventListener('blur', function () {
        validateField(input, true);
        refreshNextDisabled();
      });
      input.addEventListener('change', function () {
        if (input.getAttribute('data-step-invalid') === '1') {
          validateField(input, true);
        }
        refreshNextDisabled();
      });
      var isTextLike = input.tagName === 'INPUT'
        && ['text', 'email', 'tel', 'date', 'number', ''].indexOf(input.type) !== -1;
      if (isTextLike) {
        input.addEventListener('input', function () {
          if (input.getAttribute('data-step-invalid') === '1') {
            validateField(input, true);
          }
          refreshNextDisabled();
        });
      }
    });

    // Consent checkbox change re-runs documents-step validation.
    var consent = document.querySelector('[data-personal-data-consent]');
    if (consent) {
      consent.addEventListener('change', function () {
        // The consent input itself carries data-step-required="documents"
        // so step-1 validation covers it automatically.
        refreshNextDisabled();
      });
    }

    // member_same_address_as_guardian change flips the waiver for
    // member_actual_address — re-run member-step validation.
    var sameAddrCb = document.getElementById('id_member_same_address_as_guardian');
    if (sameAddrCb) {
      sameAddrCb.addEventListener('change', function () {
        // Clear stale error on the waived field, then re-validate.
        var addr = document.getElementById('id_member_actual_address');
        if (addr) {
          if (sameAddrCb.checked) clearError(addr);
          if (addr.getAttribute('data-step-invalid') === '1' && !sameAddrCb.checked) {
            validateField(addr, true);
          }
        }
        refreshNextDisabled();
      });
    }
  }

  function bindAutoSave() {
    if (!form) return;
    var elements = form.querySelectorAll('input, select, textarea');
    elements.forEach(function (el) {
      if (el.type === 'file') return;
      if (el.type === 'submit' || el.type === 'button') return;
      el.addEventListener('input', function () {
        scheduleAutoSave();
      });
      el.addEventListener('change', function () {
        scheduleAutoSave();
      });
      el.addEventListener('blur', function () {
        flushAutoSave();
      });
    });
  }

  // Stepper click navigation
  indicators.forEach(function (indicator, i) {
    indicator.addEventListener('click', function () {
      showStep(i);
    });
  });

  // File dropzone preview + review step status update
  function initDropzone(input) {
    input.addEventListener('change', function () {
      var file = input.files[0];
      var label = input.closest('.fk-dropzone');
      if (!label) return;
      var span = label.querySelector('span');
      if (!span) return;
      if (!file) return;
      if (file.type.startsWith('image/')) {
        var reader = new FileReader();
        reader.onload = function (e) {
          span.innerHTML = '<img class="fk-dropzone-preview" src="' + e.target.result + '" alt="">';
        };
        reader.readAsDataURL(file);
      } else {
        span.innerHTML =
          '<div class="fk-dropzone-icon">📄</div>' +
          '<div class="fk-dropzone-title">' + file.name + '</div>' +
          '<div class="fk-dropzone-meta">' + (file.size / 1024).toFixed(0) + ' KB</div>';
      }
      var reviewEl = document.querySelector('[data-review-for="' + input.id + '"]');
      if (reviewEl) reviewEl.textContent = 'Augšupielādēts ✓';
      // File uploads land via async_upload.js; once a file is present the
      // documents-step gating must re-check.
      refreshNextDisabled();
    });
  }

  document.querySelectorAll('.fk-dropzone input[type="file"]').forEach(initDropzone);

  document.addEventListener('click', function (e) {
    if (e.target.matches('[data-wizard-next]') || e.target.closest('[data-wizard-next]')) {
      var stepOk = validateStep(current);
      if (stepOk && current < total - 1) {
        showStep(current + 1);
      } else if (!stepOk) {
        // Surface inline errors on every required field of the current step
        // so the user sees what's blocking them.
        stepInputs(current).forEach(function (input) {
          validateField(input, true);
        });
        refreshNextDisabled();
      }
    }
    if (e.target.matches('[data-wizard-prev]') || e.target.closest('[data-wizard-prev]')) {
      if (current > 0) {
        showStep(current - 1);
      }
    }
  });

  bindStepGating();
  bindAutoSave();

  var startAttr = document.querySelector('[data-wizard-start]');
  var startStep = startAttr ? parseInt(startAttr.getAttribute('data-wizard-start'), 10) : 0;
  showStep(isNaN(startStep) || startStep < 0 || startStep >= total ? 0 : startStep);

  // ---- Public test hook -----------------------------------------------------
  window.__fkWizard = {
    validateStep: validateStep,
    scheduleAutoSave: scheduleAutoSave,
    getSaveState: function () {
      return saveIndicator ? saveIndicator.getAttribute('data-save-state') : null;
    }
  };
})();
