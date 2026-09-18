/* Verification-code auto-check — progressive enhancement for /register/verify/.
 *
 * When this script runs, entering/pasting/autofilling exactly six digits
 * triggers a read-only AJAX preflight against /register/verify/check/.
 * Only when the endpoint answers {"valid": true} does the script hand off
 * to the existing native form POST — that POST remains the sole consumer
 * of the code (login, session, analytics, redirect all stay server-side).
 *
 * Duplicate-submit guard (approved OTP fix): a six-digit entry causes AT
 * MOST ONE native form submission.  The script owns the button and input
 * state — locked while a preflight or the native handoff is in flight,
 * restored only after an invalid verdict or a network failure — and
 * intercepts the form's submit event so a racing manual click or Enter
 * can never open a second submission path.  The one deliberate
 * programmatic submit fires only after a valid verdict.
 *
 * A verdict whose checked digits no longer match the live input is stale
 * (the parent edited or pasted other digits while the request was in
 * flight): it neither submits nor labels the input; instead the current
 * six-digit value gets its own check once the request settles.
 *
 * The manual "Apstiprināt" button stays the no-JavaScript fallback: the
 * native POST works unchanged when this script is absent.
 */
(function () {
  'use strict';

  var form = document.querySelector('[data-verify-form]');
  if (!form) return;

  var input = form.querySelector('[data-verify-code-input]');
  var errorRegion = form.querySelector('[data-verify-error]');
  if (!input || !errorRegion) return;

  var button = form.querySelector('[data-verify-submit]');

  var CHECK_URL = '/register/verify/check/';
  var CODE_PATTERN = /^[0-9]{6}$/;
  var GENERIC_INVALID = 'Nederīgs vai noilgušs kods.';
  var CHECK_UNAVAILABLE = 'Koda pārbaude nav pieejama. Mēģiniet vēlreiz vai nospiediet „Apstiprināt”.';

  // --- State machine -------------------------------------------------
  // idle        → checking (six digits, preflight fired)
  // checking    → submitting (valid verdict handoff) | idle (invalid/network)
  // submitting  → (navigation; page leaves) — never re-enters checking
  var inFlight = false;   // preflight request outstanding
  var submitting = false; // native submission begun (handoff or manual)
  var allowProgrammaticSubmit = false; // one-shot pass for the valid verdict
  var lastCheckedCode = null;

  function lockUi() {
    if (button) button.disabled = true;
    input.readOnly = true;
  }

  function unlockUi() {
    if (button) button.disabled = false;
    input.readOnly = false;
  }

  function csrfToken() {
    var hidden = form.querySelector('input[name="csrfmiddlewaretoken"]');
    if (hidden && hidden.value) return hidden.value;
    var match = document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[2]) : '';
  }

  function showError(message) {
    errorRegion.textContent = message;
  }

  function clearError() {
    errorRegion.textContent = '';
  }

  function runCheck(checkedCode) {
    inFlight = true;
    lastCheckedCode = checkedCode;
    lockUi(); // button + input frozen for the whole preflight window
    var stale = false;

    // A verdict for since-edited digits must do nothing but let the live
    // value continue: forget the discarded check so those exact digits
    // can earn a fresh verdict if they come back.
    function discardIfStale() {
      if (checkedCode === input.value.trim()) return false;
      stale = true;
      lastCheckedCode = null;
      return true;
    }

    var body = new URLSearchParams();
    body.append('code', checkedCode);
    var token = csrfToken();
    if (token) body.append('csrfmiddlewaretoken', token);

    fetch(CHECK_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
        'X-CSRFToken': token,
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: body.toString(),
      credentials: 'same-origin',
    })
      .then(function (response) {
        if (!response.ok) throw new Error('check_rejected');
        return response.json();
      })
      .then(function (payload) {
        if (discardIfStale()) return;
        if (payload && payload.valid === true) {
          // Accepted preflight for the digits still on screen: arm the
          // one-shot pass, then hand off to the native path so server-side
          // verification owns consumption.  No further submit ever fires.
          submitting = true;
          allowProgrammaticSubmit = true;
          form.requestSubmit();
          return;
        }
        // Valid:false verdict — restore the manual path for a retry.
        lastCheckedCode = null;
        unlockUi();
        showError(GENERIC_INVALID);
      })
      .catch(function () {
        if (discardIfStale()) return;
        // Network failure or invalid JSON body: keep the entered digits,
        // show the generic Latvian hint, manual submit available again.
        lastCheckedCode = null;
        unlockUi();
        showError(CHECK_UNAVAILABLE);
      })
      .then(function () {
        inFlight = false;
        if (stale) {
          // A stale response must not swallow six digits typed while it
          // was in flight — replay the same gated path (pattern + dedupe
          // guards keep this from duplicating a check or a submission).
          onInput();
          if (!inFlight && !submitting) unlockUi();
        }
      });
  }

  function onInput() {
    clearError();
    var code = input.value.trim();
    if (!CODE_PATTERN.test(code)) return;
    if (submitting || inFlight) return;  // never overlap checks or submits
    if (code === lastCheckedCode) return; // never re-check unchanged digits
    runCheck(code);
  }

  // Single owner of every submission path: manual button click, Enter
  // (implicit submission), and the one programmatic handoff all surface
  // here.  Anything beyond the first submit is prevented outright.
  form.addEventListener('submit', function (event) {
    if (allowProgrammaticSubmit) {
      // The single deliberate handoff armed by the valid verdict.
      allowProgrammaticSubmit = false;
      submitting = true;
      lockUi();
      return; // let this one native POST through untouched
    }
    if (submitting || inFlight) {
      // A manual click/Enter racing the preflight or a submission already
      // begun: structurally impossible second submit.
      event.preventDefault();
      return;
    }
    // Deliberate manual submission while idle: claim it and freeze the UI.
    submitting = true;
    lockUi();
  });

  input.addEventListener('input', onInput);
})();
