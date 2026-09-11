/* Verification-code auto-check — progressive enhancement for /register/verify/.
 *
 * When this script runs, entering/pasting/autofilling exactly six digits
 * triggers a read-only AJAX preflight against /register/verify/check/.
 * Only when the endpoint answers {"valid": true} does the script hand off
 * to the existing native form POST — that POST remains the sole consumer
 * of the code (login, session, analytics, redirect all stay server-side).
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

  var CHECK_URL = '/register/verify/check/';
  var CODE_PATTERN = /^[0-9]{6}$/;
  var GENERIC_INVALID = 'Nederīgs vai noilgušs kods.';
  var CHECK_UNAVAILABLE = 'Koda pārbaude nav pieejama. Mēģiniet vēlreiz vai nospiediet „Apstiprināt”.';

  var inFlight = false;
  var lastCheckedCode = null;

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
          // Accepted preflight for the digits still on screen: hand off to
          // the native path so server-side verification owns consumption.
          form.requestSubmit();
          return;
        }
        // Valid:false verdict — let a later edit re-check the same digits.
        lastCheckedCode = null;
        showError(GENERIC_INVALID);
      })
      .catch(function () {
        if (discardIfStale()) return;
        // Network failure or invalid JSON body: keep the entered digits,
        // show the generic Latvian hint, manual submit still available.
        lastCheckedCode = null;
        showError(CHECK_UNAVAILABLE);
      })
      .then(function () {
        inFlight = false;
        // A stale response must not swallow six digits typed while it was
        // in flight — replay the same gated path (pattern + dedupe guards
        // keep this from duplicating a check or a submission).
        if (stale) onInput();
      });
  }

  function onInput() {
    clearError();
    var code = input.value.trim();
    if (!CODE_PATTERN.test(code)) return;
    if (inFlight) return;                // never overlap preflight requests
    if (code === lastCheckedCode) return; // never re-check unchanged digits
    runCheck(code);
  }

  input.addEventListener('input', onInput);
})();
