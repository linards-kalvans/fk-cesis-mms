(function () {
  'use strict';

  document.querySelectorAll('[data-agreement-preview]').forEach(function (root) {
    var status = root.querySelector('[data-preview-status]');
    var paper = root.querySelector('[data-preview-paper]');
    var image = root.querySelector('[data-preview-image]');
    var navigation = root.querySelector('[data-preview-navigation]');
    var pageLabel = root.querySelector('[data-preview-page]');
    var previous = root.querySelector('[data-preview-prev]');
    var next = root.querySelector('[data-preview-next]');
    var expand = root.querySelector('[data-preview-expand]');
    var retry = root.querySelector('[data-preview-retry]');
    var dialog = root.querySelector('[data-preview-dialog]');
    var pages = [];
    var current = 0;
    var started = false;
    var attempts = 0;

    function failure() {
      status.hidden = false;
      status.textContent = root.dataset.previewError;
      retry.hidden = false;
      paper.hidden = true;
      navigation.hidden = true;
      expand.disabled = true;
    }

    function showPage() {
      status.hidden = false;
      status.textContent = root.dataset.previewLoading;
      image.src = pages[current];
      image.alt = root.dataset.previewPageLabel + ' ' + (current + 1) + ' / ' + pages.length;
      pageLabel.textContent = image.alt;
      previous.disabled = current === 0;
      next.disabled = current === pages.length - 1;
      paper.scrollTop = 0;
    }

    image.addEventListener('load', function () {
      status.hidden = true;
      paper.hidden = false;
      navigation.hidden = false;
      expand.disabled = typeof dialog.showModal !== 'function';
    });
    image.addEventListener('error', failure);

    function load() {
      if (document.hidden) {
        document.addEventListener('visibilitychange', load, { once: true });
        return;
      }
      attempts += 1;
      fetch(root.dataset.previewUrl, { credentials: 'same-origin', cache: 'no-store' })
        .then(function (response) {
          if (response.status === 202 && attempts < 20) {
            window.setTimeout(load, 2000);
            return null;
          }
          if (!response.ok || response.status === 202) throw new Error('unavailable');
          return response.json();
        })
        .then(function (data) {
          if (!data) return;
          if (!Array.isArray(data.pages) || !data.pages.length) throw new Error('empty');
          pages = data.pages;
          current = 0;
          showPage();
        })
        .catch(failure);
    }

    previous.addEventListener('click', function () { if (current > 0) { current -= 1; showPage(); } });
    next.addEventListener('click', function () { if (current < pages.length - 1) { current += 1; showPage(); } });
    retry.addEventListener('click', function () {
      attempts = 0;
      retry.hidden = true;
      status.textContent = root.dataset.previewLoading;
      load();
    });
    expand.addEventListener('click', function () {
      root.querySelector('[data-preview-expanded]').appendChild(root.querySelector('[data-preview-content]'));
      dialog.showModal();
    });
    root.querySelector('[data-preview-close]').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) {
        var bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right ||
            event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
      }
    });
    dialog.addEventListener('close', function () {
      root.querySelector('[data-preview-home]').appendChild(root.querySelector('[data-preview-content]'));
      expand.focus();
    });

    // Wizard panels are hidden until visited: avoid fetching on earlier steps.
    if ('IntersectionObserver' in window) {
      var observer = new IntersectionObserver(function (entries) {
        if (!started && entries.some(function (entry) { return entry.isIntersecting; })) {
          started = true;
          observer.disconnect();
          load();
        }
      });
      observer.observe(root);
    } else {
      load();
    }
  });
})();
