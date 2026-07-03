from apps.agreements.messages import get_agreement_error_message


def test_known_code_returns_latvian():
    assert get_agreement_error_message("auth_failed") == (
        "DocuSeal autentifikācija neizdevās. Pārbaudiet API atslēgu."
    )


def test_unknown_code_returns_generic_latvian():
    msg = get_agreement_error_message("something_unexpected")
    assert msg == "Radās kļūda saziņā ar DocuSeal. Mēģiniet vēlreiz."


def test_empty_code_returns_generic():
    assert get_agreement_error_message("") == (
        "Radās kļūda saziņā ar DocuSeal. Mēģiniet vēlreiz."
    )
