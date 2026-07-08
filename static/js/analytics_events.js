// Analytics event tracker (P10).
//
// Declarative event tracking for parent-facing pages. Two trigger types:
//   - click: any element with [data-analytics-event] fires that event name
//     on click (event delegation on document)
//   - impression: any element with [data-analytics-impression] fires on
//     DOMContentLoaded
//
// All props are derived from data-analytics-* attributes. The tracker no-ops
// if window.plausible is not present (Plausible sets it itself, or the
// analytics/browser.html stub does). No PII: the tracker never reads form
// values, user objects, or session keys.

(function () {
  function send(name, props) {
    if (!name || typeof window.plausible !== 'function') return;
    window.plausible(name, { props: props || {} });
  }

  // Map of kebab-case HTML attribute suffix → snake_case Plausible prop name.
  // The HTML attribute is rendered by Django templates (Django only lowercases
  // attribute names; the templates use kebab-case for readability). Reading by
  // the exact kebab string avoids any camel↔kebab string surgery and keeps the
  // server-side allowlist in apps.analytics.sanitize (snake_case) authoritative.
  var PROP_ATTRS = {
    'data-analytics-page-area': 'page_area',
    'data-analytics-event-source': 'event_source',
    'data-analytics-application-status': 'application_status',
    'data-analytics-referral-code': 'referral_code',
    'data-analytics-error-kind': 'error_kind',
  };

  function propsFrom(el) {
    var props = {};
    // Base props (e.g. referral_code) are bootstrapped by the partial before
    // this script runs. Element-level data-analytics-* attributes override.
    if (window.fkAnalyticsBaseProps && typeof window.fkAnalyticsBaseProps === 'object') {
      for (var baseKey in window.fkAnalyticsBaseProps) {
        if (Object.prototype.hasOwnProperty.call(window.fkAnalyticsBaseProps, baseKey)) {
          props[baseKey] = window.fkAnalyticsBaseProps[baseKey];
        }
      }
    }
    for (var attr in PROP_ATTRS) {
      if (!Object.prototype.hasOwnProperty.call(PROP_ATTRS, attr)) continue;
      var value = el.getAttribute(attr);
      if (value) {
        props[PROP_ATTRS[attr]] = value;
      }
    }
    return props;
  }

  document.addEventListener('click', function (event) {
    var target = event.target.closest('[data-analytics-event]');
    if (!target) return;
    send(target.getAttribute('data-analytics-event'), propsFrom(target));
  });

  document.addEventListener('DOMContentLoaded', function () {
    var nodes = document.querySelectorAll('[data-analytics-impression]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      send(el.getAttribute('data-analytics-impression'), propsFrom(el));
    }
  });
})();
