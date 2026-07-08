"""Shared fixtures for tests/analytics/.

Re-exports registrations-scoped fixtures that browser-hook tests need.
"""

from tests.registrations.conftest import (  # noqa: F401
    draft_application,
    draft_with_documents,
    guardian_identity_file,
    kit_sizes,
    member_identity_file,
    member_portrait_file,
    submit_payload,
)
