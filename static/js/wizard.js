(function () {
  'use strict';

  var steps = document.querySelectorAll('.fk-wizard-step');
  if (!steps.length) return;

  var indicators = document.querySelectorAll('.fk-stepper .fk-step');
  var mobileCount = document.querySelector('.fk-mobile-step-count');
  var mobileLabel = document.querySelector('.fk-mobile-step-label');
  var progressLine = document.querySelector('.fk-progress-line span');

  var current = 0;
  var total = steps.length;

  function showStep(n) {
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
    window.scrollTo(0, 0);
  }

  function validateStep(n) {
    var step = steps[n];
    var inputs = step.querySelectorAll('input[required], select[required], textarea[required]');
    var ok = true;
    inputs.forEach(function (input) {
      if (!input.value.trim()) {
        input.classList.add('fk-input--error');
        ok = false;
      } else {
        input.classList.remove('fk-input--error');
      }
    });
    return ok;
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
    });
  }

  document.querySelectorAll('.fk-dropzone input[type="file"]').forEach(initDropzone);

  // Personal ID blur validation (format: DDDDDD-DDDDD)
  var pidPattern = /^\d{6}-\d{5}$/;
  ['id_guardian_personal_id', 'id_member_personal_id'].forEach(function (id) {
    var input = document.getElementById(id);
    if (!input) return;
    var errEl = document.createElement('p');
    errEl.className = 'fk-form-error';
    errEl.textContent = 'Ievadiet personas kodu formātā DDDDDD-DDDDD.';
    errEl.hidden = true;
    var container = input.closest('.fk-form-field');
    if (container) container.appendChild(errEl);
    input.addEventListener('blur', function () {
      var val = input.value.trim();
      var invalid = val && !pidPattern.test(val);
      errEl.hidden = !invalid;
      input.classList.toggle('fk-input--error', !!invalid);
    });
    input.addEventListener('input', function () {
      if (pidPattern.test(input.value.trim())) {
        errEl.hidden = true;
        input.classList.remove('fk-input--error');
      }
    });
  });

  document.addEventListener('click', function (e) {
    if (e.target.matches('[data-wizard-next]') || e.target.closest('[data-wizard-next]')) {
      if (validateStep(current) && current < total - 1) {
        showStep(current + 1);
      }
    }
    if (e.target.matches('[data-wizard-prev]') || e.target.closest('[data-wizard-prev]')) {
      if (current > 0) {
        showStep(current - 1);
      }
    }
  });

  var startAttr = document.querySelector('[data-wizard-start]');
  var startStep = startAttr ? parseInt(startAttr.getAttribute('data-wizard-start'), 10) : 0;
  showStep(isNaN(startStep) || startStep < 0 || startStep >= total ? 0 : startStep);
})();
