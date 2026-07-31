"""Shared test helpers."""

from apps.accounts.models import ParentAccount

_counter = {"n": 0}


def _split_full_name(full_name: str) -> tuple[str, str]:
    """Test-only local split. Last token is family name; earlier tokens are first name."""
    parts = str(full_name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def make_guardian(*, email="", phone="", account=None, **guardian_kwargs):
    """Create a Guardian linked to a ParentAccount.

    Pass ``account`` to reuse one, or ``email``/``phone`` to mint a fresh
    account (a unique email is generated when none is given). ``email``/
    ``phone`` live on the account; remaining kwargs (first_name, family_name,
    full_name, personal_id, address, external_client_id) go on the Guardian.

    When ``full_name`` is passed without explicit ``first_name``/``family_name``,
    the legacy full_name is split using a local test-only rule (last token =
    family name).
    """
    from apps.members.models import Guardian

    if account is None:
        if not email:
            _counter["n"] += 1
            email = f"guardian{_counter['n']}@example.test"
        account = ParentAccount.objects.create(email=email.lower(), phone=phone)

    full_name_legacy = guardian_kwargs.pop("full_name", None)
    first_name = guardian_kwargs.pop("first_name", "")
    family_name = guardian_kwargs.pop("family_name", "")
    if full_name_legacy and not (first_name or family_name):
        first_name, family_name = _split_full_name(full_name_legacy)

    guardian = Guardian(
        parent_account=account,
        first_name=first_name,
        family_name=family_name,
        **guardian_kwargs,
    )
    guardian.save()
    return guardian
