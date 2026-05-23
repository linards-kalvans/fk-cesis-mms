/* P3.5 — Async document upload + OCR status polling + prefill/suggest UX.
 *
 * Progressive enhancement: when this script runs, file inputs marked with
 * `data-async-upload` POST to the async endpoint as soon as the user picks
 * a file. The page then polls the status endpoint, renders progress, and
 * (on completion) either prefills empty fields or shows a suggestion chip
 * beside fields the user already filled in. When the script is absent
 * (no JS, blocked, etc.) the synchronous form submit path still works.
 */
(function () {
  'use strict';

  var ROOT = document.querySelector('[data-async-upload-root]');
  if (!ROOT) return;

  var APPLICATION_ID = ROOT.getAttribute('data-application-id');
  var UPLOAD_URL = ROOT.getAttribute('data-upload-url');
  var STATUS_URL_TEMPLATE = ROOT.getAttribute('data-status-url-template');
  var CSRF_TOKEN = (function () {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  })();

  if (!APPLICATION_ID || !UPLOAD_URL || !STATUS_URL_TEMPLATE) return;

  var POLL_INITIAL_MS = 1000;
  var POLL_MAX_MS = 5000;
  var POLL_DEADLINE_MS = 30000;

  /**
   * Decide whether OCR should prefill, suggest, or do nothing for a field.
   * Mirrors apps.registrations.presentation.classify_field_action (Phase 4).
   */
  function classifyFieldAction(currentValue, ocrValue) {
    var cur = (currentValue || '').trim();
    var ocr = (ocrValue || '').trim();
    if (!ocr) return 'noop';
    if (!cur) return 'prefill';
    if (cur.toLowerCase() === ocr.toLowerCase()) return 'noop';
    return 'suggest';
  }

  function statusUrlFor(documentId) {
    return STATUS_URL_TEMPLATE.replace(
      '__document_id__',
      encodeURIComponent(documentId)
    );
  }

  function setProgressLabel(slot, text) {
    if (!slot) return;
    slot.textContent = text;
    slot.removeAttribute('hidden');
  }

  var TOAST_AUTO_DISMISS_MS = 4000;

  function renderSpinner(slot, label) {
    if (!slot) return;
    slot.removeAttribute('hidden');
    slot.setAttribute('data-state', 'running');
    slot.innerHTML =
      '<div class="fk-spinner" role="status" aria-live="polite" data-spinner>'
      + '<span class="fk-spinner__dot" aria-hidden="true"></span>'
      + '<span class="fk-spinner__label"></span>'
      + '</div>';
    slot.querySelector('.fk-spinner__label').textContent =
      label || 'Apstrādājam dokumentu…';
  }

  function renderSuccessToast(slot, recognizedName) {
    if (!slot) return;
    slot.removeAttribute('hidden');
    slot.setAttribute('data-state', 'completed');
    var message = recognizedName
      ? ('Dokumenta apstrāde pabeigta. Persona atpazīta kā ' + recognizedName + '.')
      : 'Dokumenta apstrāde pabeigta.';
    slot.innerHTML =
      '<div class="fk-toast fk-toast--success" role="status" aria-live="polite" '
      + 'data-toast data-toast-tone="success">'
      + '<span class="fk-toast__message"></span>'
      + '</div>';
    slot.querySelector('.fk-toast__message').textContent = message;
    // Auto-dismiss after a short delay.
    setTimeout(function () { dismissToast(slot); }, TOAST_AUTO_DISMISS_MS);
  }

  function dismissToast(slot) {
    if (!slot) return;
    var toast = slot.querySelector('[data-toast]');
    if (toast) toast.remove();
    if (!slot.children || slot.children.length === 0) {
      slot.setAttribute('hidden', '');
    }
  }

  function renderFailure(slot, message) {
    if (!slot) return;
    slot.removeAttribute('hidden');
    slot.setAttribute('data-state', 'failed');
    slot.innerHTML =
      '<div class="fk-inline-error" role="alert" data-inline-error></div>';
    slot.querySelector('[data-inline-error]').textContent = message
      || 'Neizdevās apstrādāt dokumentu automātiski. Lūdzu, aizpildi laukus manuāli.';
  }

  function applyExtractedFields(extractedFields) {
    Object.keys(extractedFields).forEach(function (fieldName) {
      var value = extractedFields[fieldName];
      var input = document.querySelector('[name="' + fieldName + '"]');
      if (!input) return;
      var action = classifyFieldAction(input.value, value);
      if (action === 'prefill') {
        input.value = value;
        markBadge(input, 'ocr');
        input.dispatchEvent(new Event('change', { bubbles: true }));
      } else if (action === 'suggest') {
        renderSuggestionChip(input, value);
      }
    });
  }

  function markBadge(input, kind) {
    var existing = input.parentNode.querySelector('[data-source-badge]');
    if (existing) existing.remove();
    var badge = document.createElement('span');
    badge.setAttribute('data-source-badge', kind);
    badge.className = 'fk-source-badge fk-source-badge--' + kind;
    badge.textContent = kind === 'ocr' ? 'No OCR dokumenta' : kind;
    input.parentNode.appendChild(badge);
  }

  function renderSuggestionChip(input, suggestedValue) {
    // Avoid duplicate chips for the same field/value.
    var existing = input.parentNode.querySelector('[data-ocr-suggestion]');
    if (existing && existing.getAttribute('data-suggested-value') === suggestedValue) {
      return;
    }
    if (existing) existing.remove();

    var chip = document.createElement('span');
    chip.className = 'fk-ocr-suggestion';
    chip.setAttribute('data-ocr-suggestion', 'true');
    chip.setAttribute('data-suggested-value', suggestedValue);
    chip.innerHTML =
      '<span class="fk-ocr-suggestion__label">OCR: </span>'
      + '<span class="fk-ocr-suggestion__value"></span>'
      + ' <button type="button" class="fk-ocr-suggestion__accept">Pieņemt</button>'
      + ' <button type="button" class="fk-ocr-suggestion__dismiss" aria-label="Noraidīt">×</button>';
    chip.querySelector('.fk-ocr-suggestion__value').textContent = suggestedValue;

    chip.querySelector('.fk-ocr-suggestion__accept').addEventListener('click', function () {
      input.value = suggestedValue;
      markBadge(input, 'ocr');
      input.dispatchEvent(new Event('change', { bubbles: true }));
      chip.remove();
    });
    chip.querySelector('.fk-ocr-suggestion__dismiss').addEventListener('click', function () {
      chip.remove();
    });
    input.parentNode.appendChild(chip);
  }

  function pollStatus(documentId, progressSlot, deadline, intervalMs) {
    if (Date.now() > deadline) {
      setProgressLabel(progressSlot, 'OCR aizņem ilgāk nekā parasti — vari turpināt aizpildīt manuāli.');
      return;
    }
    var url = statusUrlFor(documentId);
    fetch(url, { credentials: 'same-origin' })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        if (payload.ocr_status === 'completed') {
          var fields = payload.extracted_fields || {};
          var name = fields.guardian_full_name || fields.member_full_name || '';
          renderSuccessToast(progressSlot, name);
          applyExtractedFields(fields);
          return;
        }
        if (payload.ocr_status === 'failed') {
          renderFailure(progressSlot, payload.ocr_error_message);
          return;
        }
        // Still pending/running — keep polling with mild backoff.
        var nextInterval = Math.min(intervalMs + 500, POLL_MAX_MS);
        renderSpinner(progressSlot);
        scheduleNextPoll(documentId, progressSlot, deadline, nextInterval);
      })
      .catch(function () {
        var nextInterval = Math.min(intervalMs + 1000, POLL_MAX_MS);
        scheduleNextPoll(documentId, progressSlot, deadline, nextInterval);
      });
  }

  function scheduleNextPoll(documentId, progressSlot, deadline, intervalMs) {
    // Pause polling when the tab is hidden — the browser already throttles
    // setTimeout in background tabs, but resuming on visibilitychange gives
    // a snappier user experience when the parent comes back to the tab.
    if (document.hidden) {
      var resume = function () {
        document.removeEventListener('visibilitychange', resume);
        pollStatus(documentId, progressSlot, deadline, intervalMs);
      };
      document.addEventListener('visibilitychange', resume, { once: true });
      return;
    }
    setTimeout(function () {
      pollStatus(documentId, progressSlot, deadline, intervalMs);
    }, intervalMs);
  }

  function bindFileInput(input) {
    var kind = input.getAttribute('data-async-upload');
    if (!kind) return;
    var progressSlot = (function () {
      var slotId = input.getAttribute('data-progress-slot');
      return slotId ? document.getElementById(slotId) : null;
    })();

    input.addEventListener('change', function () {
      if (!input.files || !input.files.length) return;
      var file = input.files[0];
      setProgressLabel(progressSlot, 'Augšupielādē…');

      var formData = new FormData();
      formData.append('file', file);
      formData.append('kind', kind);
      if (CSRF_TOKEN) formData.append('csrfmiddlewaretoken', CSRF_TOKEN);

      fetch(UPLOAD_URL, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: CSRF_TOKEN ? { 'X-CSRFToken': CSRF_TOKEN } : {},
      })
        .then(function (response) {
          if (!response.ok) {
            return response.json().then(function (body) {
              throw new Error(body.error || 'upload_failed');
            });
          }
          return response.json();
        })
        .then(function (payload) {
          if (payload.ocr_status === 'not_requested') {
            setProgressLabel(progressSlot, 'Augšupielādēts');
            return;
          }
          renderSpinner(progressSlot);
          pollStatus(
            payload.document_id,
            progressSlot,
            Date.now() + POLL_DEADLINE_MS,
            POLL_INITIAL_MS
          );
        })
        .catch(function () {
          renderFailure(
            progressSlot,
            'Augšupielāde neizdevās. Pamēģini vēlreiz vai aizpildi laukus manuāli.'
          );
        });
    });
  }

  // Bind every async-enabled file input on the page.
  Array.prototype.forEach.call(
    document.querySelectorAll('input[type="file"][data-async-upload]'),
    bindFileInput
  );

  // On page load, start polling any documents that arrived already in
  // PENDING state — typically because the parent saved a draft on
  // /applications/new/ (synchronous form path) and OCR is still running
  // in the worker by the time the workspace renders.
  (function pollPendingDocumentsOnLoad() {
    var raw = ROOT.getAttribute('data-pending-by-kind') || '{}';
    var pendingByKind;
    try { pendingByKind = JSON.parse(raw); } catch (e) { return; }
    Object.keys(pendingByKind).forEach(function (kind) {
      var docId = pendingByKind[kind];
      if (!docId) return;
      var input = document.querySelector(
        'input[type="file"][data-async-upload="' + kind + '"]'
      );
      var slot = null;
      if (input) {
        var slotId = input.getAttribute('data-progress-slot');
        slot = slotId ? document.getElementById(slotId) : null;
      }
      if (!slot) return;
      renderSpinner(slot);
      pollStatus(docId, slot, Date.now() + POLL_DEADLINE_MS, POLL_INITIAL_MS);
    });
  })();

  // Expose for tests / inline scripts that want to call directly.
  window.__fkAsyncUpload = {
    classifyFieldAction: classifyFieldAction,
    applyExtractedFields: applyExtractedFields,
  };
})();
