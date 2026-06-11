import pytest

pytestmark = pytest.mark.django_db


def test_preferred_payment_mode_field_exists_with_choices():
    from apps.registrations.models import RegistrationApplication

    app = RegistrationApplication()
    app.preferred_payment_mode = "installments"
    assert RegistrationApplication.PaymentMode.UPFRONT == "upfront"
    assert RegistrationApplication.PaymentMode.INSTALLMENTS == "installments"


def test_form_has_preferred_payment_mode_with_choices():
    from apps.registrations.forms import RegistrationApplicationForm

    form = RegistrationApplicationForm()
    assert "preferred_payment_mode" in form.fields
    values = [c[0] for c in form.fields["preferred_payment_mode"].choices]
    assert "upfront" in values and "installments" in values
