/*
 * P5 Slice A (Revision A) — admin doc lightbox.
 *
 * Wires a single <dialog class="mms-lightbox"> on the page. Each
 * <a data-mms-lightbox> link, when clicked, opens the dialog populated
 * with either an <img> (data-doc-kind="image") or an <iframe> (anything
 * else — typically PDFs). No frameworks; native <dialog> handles ESC.
 */
(function () {
  "use strict";

  function buildDialog() {
    var dialog = document.createElement("dialog");
    dialog.className = "mms-lightbox";

    var content = document.createElement("div");
    content.className = "mms-lightbox-content";

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "mms-lightbox-close";
    closeBtn.textContent = "Aizvērt";
    closeBtn.addEventListener("click", function () {
      dialog.close();
    });

    var slot = document.createElement("div");
    slot.className = "mms-lightbox-slot";

    content.appendChild(closeBtn);
    content.appendChild(slot);
    dialog.appendChild(content);

    // Click on backdrop (target === dialog) closes.
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) {
        dialog.close();
      }
    });

    document.body.appendChild(dialog);
    return { dialog: dialog, slot: slot };
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof HTMLDialogElement === "undefined") {
      // No <dialog> support — fall back to native target="_blank" behaviour.
      return;
    }
    var ctx = buildDialog();
    var links = document.querySelectorAll("a[data-mms-lightbox]");
    links.forEach(function (link) {
      link.addEventListener("click", function (event) {
        event.preventDefault();
        var kind = link.getAttribute("data-doc-kind") || "other";
        var href = link.getAttribute("href");
        ctx.slot.innerHTML = "";
        var node;
        if (kind === "image") {
          node = document.createElement("img");
          node.className = "mms-lightbox-image";
          node.alt = "";
          node.src = href;
        } else {
          node = document.createElement("iframe");
          node.className = "mms-lightbox-iframe";
          node.setAttribute("title", "Dokumenta priekšskatījums");
          node.src = href;
        }
        ctx.slot.appendChild(node);
        ctx.dialog.showModal();
      });
    });
  });
})();
