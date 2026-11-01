/**
 * @fileoverview Stops the name form when a first or last name is blank.
 */
(function() {
  'use strict';

  const form = document.querySelector('[data-name-form]');
  if (!form) {
    return;
  }

  form.addEventListener('submit', function(event) {
    const first = form.elements.namedItem('first_name');
    const last = form.elements.namedItem('last_name');
    const firstValue = first.value.replace(/\s+/g, ' ').trim();
    const lastValue = last.value.replace(/\s+/g, ' ').trim();
    if (firstValue && lastValue) {
      return;
    }
    event.preventDefault();
    const error = form.querySelector('[data-form-error]');
    error.hidden = false;
    error.textContent = 'Enter both a first name and a last name.';
    (firstValue ? last : first).focus();
  });
}());
