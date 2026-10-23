/* Correction-request history dialog.
 *
 * Hover/focus only reveals the server-rendered summary; it never fetches.
 * Clicking a summary link loads the authorized, server-escaped fragment into
 * a native <dialog>. Without JavaScript (or native dialog support) the same
 * link is a normal navigation to the standalone history page.
 */
(function () {
  "use strict";

  var dialog = document.querySelector("[data-correction-dialog]");
  if (!dialog || typeof dialog.showModal !== "function") {
    return;
  }

  var body = dialog.querySelector("[data-correction-body]");
  var fallback = dialog.querySelector("[data-correction-fallback]");
  var closeButton = dialog.querySelector("[data-correction-close]");
  var loadingText = "Ielādē ziņu vēsturi…";
  var errorText = "Neizdevās ielādēt ziņu vēsturi. Mēģiniet vēlreiz vai atveriet pilnu vēsturi.";
  var opener = null;
  var requestSequence = 0;
  var controller = null;

  if (!body) {
    return;
  }

  function showStatus(text) {
    var paragraph = document.createElement("p");
    paragraph.className = "hint";
    paragraph.textContent = text;
    body.textContent = "";
    body.appendChild(paragraph);
    body.setAttribute("aria-busy", "false");
  }

  function load(url) {
    var sequence = ++requestSequence;
    if (controller) {
      controller.abort();
    }
    controller = typeof AbortController === "function" ? new AbortController() : null;

    body.textContent = "";
    var status = document.createElement("p");
    status.className = "hint";
    status.textContent = loadingText;
    body.appendChild(status);
    body.setAttribute("aria-busy", "true");

    fetch(url, {
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "text/html",
      },
      signal: controller ? controller.signal : undefined,
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        /* An expired session redirects to the login page, which fetch follows
           to a 200. Reject the redirect before reading its body so the login
           page can never be injected as if it were history. */
        if (response.redirected) {
          throw new Error("Unexpected redirect");
        }
        return response.text();
      })
      .then(function (html) {
        if (sequence !== requestSequence) {
          return;
        }
        /* Only the server-rendered history fragment may be injected. */
        if (typeof html !== "string" || html.indexOf("data-correction-history") === -1) {
          throw new Error("Unexpected response");
        }
        /* Server-rendered HTML only. Correspondence is never interpolated in
           JavaScript, so escaped subject/body/note cannot become markup. */
        body.innerHTML = html;
        body.setAttribute("aria-busy", "false");
        var focusTarget = body.querySelector("h3") || body;
        focusTarget.setAttribute("tabindex", "-1");
        focusTarget.focus();
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") {
          return;
        }
        if (sequence !== requestSequence) {
          return;
        }
        body.textContent = "";
        var message = document.createElement("p");
        message.className = "callout callout--danger";
        message.textContent = errorText;
        body.appendChild(message);
        body.setAttribute("aria-busy", "false");
      });
  }

  function openFrom(trigger) {
    var url = trigger.getAttribute("href");
    if (!url) {
      return false;
    }
    opener = trigger;
    if (fallback) {
      fallback.setAttribute("href", url);
    }
    if (!dialog.open) {
      dialog.showModal();
    }
    load(url);
    return true;
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || typeof target.closest !== "function") {
      return;
    }
    var trigger = target.closest("[data-correction-open]");
    if (!trigger) {
      return;
    }
    if (openFrom(trigger)) {
      event.preventDefault();
    }
  });

  dialog.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || typeof target.closest !== "function") {
      return;
    }
    var pageLink = target.closest("[data-correction-page]");
    if (pageLink) {
      event.preventDefault();
      load(pageLink.getAttribute("href"));
      return;
    }
    /* Clicking the backdrop dispatches at the dialog element itself. */
    if (target === dialog) {
      dialog.close();
    }
  });

  if (closeButton) {
    closeButton.addEventListener("click", function () {
      dialog.close();
    });
  }

  dialog.addEventListener("close", function () {
    requestSequence += 1;
    if (controller) {
      controller.abort();
    }
    body.setAttribute("aria-busy", "false");
    if (opener) {
      opener.focus();
      opener = null;
    }
  });
})();
