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

  document.addEventListener('click', function (e) {
    if (e.target.matches('[data-wizard-next]') || e.target.closest('[data-wizard-next]')) {
      var btn = e.target.matches('[data-wizard-next]') ? e.target : e.target.closest('[data-wizard-next]');
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

  showStep(0);
})();
