"""consolidate_guardians links orphans, creates missing accounts, merges dups.

consolidate_guardians is a one-time data-migration tool: it reads the legacy
Guardian.email/phone columns to resolve orphans. Those columns were dropped in
members.0007, so these tests migrate the schema back to the members.0006 state
(where the columns still exist), exercise the function against the historical
models — exactly how the 0006 RunPython migration invokes it in production —
then restore the schema to head.
"""

import pytest

from apps.members.services import consolidate_guardians

# These tests roll the schema back and forward, so they cannot share the
# transactional test DB with the rest of the suite.
pytestmark = [pytest.mark.django_db(transaction=True)]

_AT_0006 = [
    ("members", "0006_consolidate_guardians"),
    ("accounts", "0005_emailverificationcode_code_hash"),
    ("registrations", "0010_remove_registrationapplication_guardian_declared_address_and_more"),
]


@pytest.fixture
def historical():
    """Migrate the schema back to members.0006 (legacy email/phone columns
    present), yield the historical models, then migrate forward to head."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    executor.migrate(_AT_0006)
    executor.loader.build_graph()
    state = executor.loader.project_state(_AT_0006[0])
    apps = state.apps
    try:
        yield {
            "Guardian": apps.get_model("members", "Guardian"),
            "ParentAccount": apps.get_model("accounts", "ParentAccount"),
            "Member": apps.get_model("members", "Member"),
            "RegistrationApplication": apps.get_model(
                "registrations", "RegistrationApplication"
            ),
        }
    finally:
        # Restore the schema to the latest migration for the rest of the suite.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def _run(historical):
    consolidate_guardians(
        guardian_model=historical["Guardian"],
        account_model=historical["ParentAccount"],
        member_model=historical["Member"],
        application_model=historical["RegistrationApplication"],
    )


def test_merge_repoints_applications_before_deleting_loser(historical):
    # RegistrationApplication.guardian is on_delete=PROTECT — the loser's
    # applications must be repointed to the survivor before deletion, else
    # consolidate would raise ProtectedError.
    Guardian = historical["Guardian"]
    ParentAccount = historical["ParentAccount"]
    RegistrationApplication = historical["RegistrationApplication"]
    ParentAccount.objects.create(email="ap@example.com")
    keep = Guardian.objects.create(full_name="K", email="ap@example.com", external_client_id="IN-1")
    drop = Guardian.objects.create(full_name="K dup", email="ap@example.com")
    app = RegistrationApplication.objects.create(
        status="submitted", member_full_name="Bērns", guardian=drop
    )
    _run(historical)
    app.refresh_from_db()
    assert app.guardian_id == keep.pk
    assert not Guardian.objects.filter(pk=drop.pk).exists()


def test_orphan_guardian_linked_to_existing_account_by_email(historical):
    Guardian = historical["Guardian"]
    ParentAccount = historical["ParentAccount"]
    acc = ParentAccount.objects.create(email="p@example.com", phone="+371")
    g = Guardian.objects.create(full_name="P", email="p@example.com")  # orphan
    _run(historical)
    g.refresh_from_db()
    assert g.parent_account_id == acc.pk


def test_orphan_with_no_account_gets_one_created(historical):
    Guardian = historical["Guardian"]
    g = Guardian.objects.create(full_name="Q", email="q@example.com", phone="+37122")
    _run(historical)
    g.refresh_from_db()
    assert g.parent_account is not None
    assert g.parent_account.email == "q@example.com"
    assert g.parent_account.phone == "+37122"


def test_account_phone_backfilled_from_guardian_when_empty(historical):
    Guardian = historical["Guardian"]
    ParentAccount = historical["ParentAccount"]
    acc = ParentAccount.objects.create(email="r@example.com", phone="")
    Guardian.objects.create(full_name="R", email="r@example.com", phone="+37133")
    _run(historical)
    acc.refresh_from_db()
    assert acc.phone == "+37133"


def test_duplicate_guardians_merge_to_survivor_with_external_client_id(historical):
    Guardian = historical["Guardian"]
    ParentAccount = historical["ParentAccount"]
    Member = historical["Member"]
    ParentAccount.objects.create(email="s@example.com")
    keep = Guardian.objects.create(full_name="S", email="s@example.com", external_client_id="IN-9")
    drop = Guardian.objects.create(full_name="S dup", email="s@example.com")
    m = Member.objects.create(full_name="Child", guardian=drop)
    _run(historical)
    m.refresh_from_db()
    assert m.guardian_id == keep.pk
    assert not Guardian.objects.filter(pk=drop.pk).exists()
    assert Guardian.objects.get(pk=keep.pk).external_client_id == "IN-9"


def test_idempotent_on_clean_data(historical):
    Guardian = historical["Guardian"]
    ParentAccount = historical["ParentAccount"]
    acc = ParentAccount.objects.create(email="t@example.com")
    Guardian.objects.create(full_name="T", parent_account=acc, email="t@example.com")
    _run(historical)
    _run(historical)
    assert Guardian.objects.count() == 1
