"""Shared test helpers."""

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian

_counter = {"n": 0}


def make_guardian(*, email="", phone="", account=None, **guardian_kwargs):
    """Create a Guardian linked to a ParentAccount.

    Pass ``account`` to reuse one, or ``email``/``phone`` to mint a fresh
    account (a unique email is generated when none is given). ``email``/
    ``phone`` live on the account; remaining kwargs (full_name, personal_id,
    address, external_client_id) go on the Guardian.
    """
    if account is None:
        if not email:
            _counter["n"] += 1
            email = f"guardian{_counter['n']}@example.test"
        account = ParentAccount.objects.create(email=email.lower(), phone=phone)
    return Guardian.objects.create(parent_account=account, **guardian_kwargs)
