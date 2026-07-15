"""Shared test helpers."""

from apps.accounts.models import ParentAccount

_counter = {"n": 0}


def make_guardian(*, email="", phone="", account=None, **guardian_kwargs):
    """Create a Guardian linked to a ParentAccount.

    Pass ``account`` to reuse one, or ``email``/``phone`` to mint a fresh
    account (a unique email is generated when none is given). ``email``/
    ``phone`` live on the account; remaining kwargs (first_name, family_name,
    full_name, personal_id, address, external_client_id) go on the Guardian.

    When ``full_name`` is passed without explicit ``first_name``/``family_name``,
    the legacy full_name is split using the P13 backfill rule and the mirror
    is rebuilt via ``sync_full_name()``.
    """
    from apps.members.models import Guardian

    if account is None:
        if not email:
            _counter["n"] += 1
            email = f"guardian{_counter['n']}@example.test"
        account = ParentAccount.objects.create(email=email.lower(), phone=phone)

    # P13: support first_name/family_name; backfill from full_name if needed.
    full_name_legacy = guardian_kwargs.pop("full_name", None)
    first_name = guardian_kwargs.pop("first_name", "")
    family_name = guardian_kwargs.pop("family_name", "")
    if full_name_legacy and not (first_name or family_name):
        try:
            from apps.members.models import split_guardian_full_name
            first_name, family_name = split_guardian_full_name(full_name_legacy)
        except ImportError:
            first_name = full_name_legacy
            family_name = ""

    guardian = Guardian(
        parent_account=account,
        first_name=first_name,
        family_name=family_name,
        **guardian_kwargs,
    )
    try:
        guardian.sync_full_name()
    except AttributeError:
        # P13 not yet implemented — fall back to setting full_name directly.
        if full_name_legacy:
            guardian.full_name = full_name_legacy
    guardian.save()
    return guardian
