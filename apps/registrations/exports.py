"""Column definitions + row builder for the Registration-applications CSV export."""

from apps.registrations.models import RegistrationApplication

APPLICATION_SAFE_COLUMNS = [
    "ID", "Statuss", "Bērns", "Bērna dzimšanas datums", "Vecāks",
    "Maksājuma veids", "Līguma parakstīšana", "Iesniegts", "Pārskatīts",
]
APPLICATION_SENSITIVE_EXTRA = [
    "Bērna personas kods", "Bērna adrese", "Vecāka e-pasts",
    "Vecāka tālrunis", "Vecāka personas kods", "Vecāka adrese",
]


def application_columns(*, sensitive: bool) -> list[str]:
    return (
        APPLICATION_SAFE_COLUMNS + APPLICATION_SENSITIVE_EXTRA
        if sensitive
        else list(APPLICATION_SAFE_COLUMNS)
    )


def application_row(app: RegistrationApplication, *, sensitive: bool) -> list:
    row: list = [
        app.pk,
        app.get_status_display(),
        app.member_full_name,
        app.member_birth_date,
        app.guardian_name,
        app.preferred_payment_mode,
        app.preferred_agreement_signing,
        app.submitted_at,
        app.reviewed_at,
    ]
    if sensitive:
        row += [
            app.member_personal_id,
            app.member_actual_address,
            app.guardian_contact_email,
            app.guardian_contact_phone,
            app.guardian_pid,
            app.guardian_address,
        ]
    return row
