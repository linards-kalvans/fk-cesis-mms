"""Render-smoke tests for the four P4 cross-cutting UI primitives.

Each partial is rendered through an inline template that exercises the
{% include ... with ... %} contract. Tests assert the documented DOM hooks
(class names / data attributes) and the Latvian default copy. Behavior
(auto-dismiss, polling, etc.) lands in later P4 slices.
"""

from django.template import Context, Template


def _render(template_source: str) -> str:
    return Template(template_source).render(Context({}))


def test_spinner_renders_with_default_latvian_label():
    output = _render(
        '{% include "parent_ui/includes/spinner.html" %}'
    )
    assert "Apstrādājam dokumentu" in output
    assert 'role="status"' in output
    assert "data-spinner" in output


def test_spinner_accepts_custom_label():
    output = _render(
        '{% include "parent_ui/includes/spinner.html" with label="Lūdzu uzgaidiet…" %}'
    )
    assert "Lūdzu uzgaidiet…" in output
    assert "Apstrādājam dokumentu" not in output


def test_toast_renders_message_and_tone_hook():
    output = _render(
        '{% include "parent_ui/includes/toast.html" with message="Saglabāts" tone="success" %}'
    )
    assert "Saglabāts" in output
    assert "data-toast" in output
    assert 'data-toast-tone="success"' in output
    assert 'role="status"' in output
    assert 'aria-live="polite"' in output


def test_toast_defaults_to_neutral_tone_when_unspecified():
    output = _render(
        '{% include "parent_ui/includes/toast.html" with message="Saglabāts" %}'
    )
    assert 'data-toast-tone="neutral"' in output
    assert 'role="status"' in output
    assert 'aria-live="polite"' in output


def test_toast_warning_uses_assertive_live_region():
    output = _render(
        '{% include "parent_ui/includes/toast.html" with message="Brīdinājums" tone="warning" %}'
    )
    assert 'role="alert"' in output
    assert 'aria-live="assertive"' in output


def test_empty_state_renders_title_and_body():
    output = _render(
        '{% include "parent_ui/includes/empty_state.html" '
        'with title="Nav pieteikumu" body="Sāciet jaunu reģistrāciju." %}'
    )
    assert "Nav pieteikumu" in output
    assert "Sāciet jaunu reģistrāciju." in output
    assert "data-empty-state" in output


def test_error_state_renders_title_body_and_alert_role():
    output = _render(
        '{% include "parent_ui/includes/error_state.html" '
        'with title="Radās kļūda" body="Lūdzu, mēģiniet vēlreiz." %}'
    )
    assert "Radās kļūda" in output
    assert "Lūdzu, mēģiniet vēlreiz." in output
    assert "data-error-state" in output
    assert 'role="alert"' in output


def test_empty_state_omits_title_element_when_no_title_given():
    output = _render(
        '{% include "parent_ui/includes/empty_state.html" with body="Tikai pamatteksts." %}'
    )
    assert "Tikai pamatteksts." in output
    assert "fk-empty-state__title" not in output


def test_error_state_omits_title_element_when_no_title_given():
    output = _render(
        '{% include "parent_ui/includes/error_state.html" with body="Tikai pamatteksts." %}'
    )
    assert "Tikai pamatteksts." in output
    assert "fk-error-state__title" not in output
