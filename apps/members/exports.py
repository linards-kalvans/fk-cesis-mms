"""Column definitions + row builder for the Members CSV export."""

from apps.members.models import Member

MEMBER_SAFE_COLUMNS = ["ID", "Vārds uzvārds", "Dzimšanas datums", "Vecāks", "Treniņu grupa"]
MEMBER_SENSITIVE_EXTRA = ["Personas kods", "Vecāka e-pasts", "Vecāka tālrunis", "Vecāka adrese"]


def member_columns(*, sensitive: bool) -> list[str]:
    return MEMBER_SAFE_COLUMNS + MEMBER_SENSITIVE_EXTRA if sensitive else list(MEMBER_SAFE_COLUMNS)


def member_row(member: Member, *, sensitive: bool) -> list:
    g = member.guardian  # non-null FK
    row: list = [
        member.pk,
        member.full_name,
        member.birth_date,
        g.full_name,
        member.training_group.name if member.training_group_id else "",
    ]
    if sensitive:
        row += [member.personal_id, g.email, g.phone, g.address]
    return row
