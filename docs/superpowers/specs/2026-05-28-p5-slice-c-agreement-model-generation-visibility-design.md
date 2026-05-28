# P5 Slice C — Agreement model + generation + visibility

**Status:** Approved 2026-05-28. Awaiting implementation plan.
**Spec for:** P5 acceptance items 5, 7, 11 only. Items 6, 8, 9, 10 → Slice D.
**Predecessor:** P5 Slice A (admin review polish) + Slice A.1 (templated emails) + Slice B (training-group assignment) shipped on `dev`, awaiting merge to `main`.

## Context

P5 item 5 says an agreement is generated after approval; item 7 says manual signing state is tracked (`generated`, `sent/shared`, `signed`); item 11 says parent and admin visibility is clear with no misleading in-app e-sign UX. Slice C delivers all three behind an internal-only Agreement domain. No external integration yet — DocuSeal lands in Slice D, which builds directly on the model and state machine that Slice C ships.

The project already has `RegistrationApplication.preferred_agreement_signing` (a `TextChoices` enum of `electronic` / `paper`, currently `blank=True`) that the parent picks during registration but that nothing acts on yet. Slice C reads this preference at agreement-creation time and snapshots it onto the Agreement.

## Decisions locked in (no re-debate)

1. **App boundary** — new `apps/agreements/` Django app. Matches the project's existing per-domain split.
2. **Attachment** — `OneToOneField(Member, on_delete=CASCADE, related_name="agreement")`. Member is the live record post-approval; application is the historical intake snapshot.
3. **States** — `generated → sent → signed`, plus `void` as a terminal escape valve. No `expired` (not actionable until Slice D).
4. **Default signing path on creation** — `electronic` when `application.preferred_agreement_signing` is empty. Honour the parent's pick when set.
5. **Signing-path override** — staff may flip `electronic ⇄ paper` at any state via the admin module (no lock).
6. **Email notifications** — Django sends plain-text Latvian emails on `sent` and `signed`, today, for both paths. Slice D will add the suppression logic for the electronic path once DocuSeal handles its own notifications. Nothing on `generated` or `void`.
7. **Void is terminal** — no regenerate-after-void path in Slice C. If a voided agreement needs replacing, the team handles it via DB intervention or a follow-up slice with an FK + `active` flag.

## Architecture

### Model — `apps/agreements/models.py`

```python
class Agreement(TimeStampedModel):
    class State(models.TextChoices):
        GENERATED = "generated", "Sagatavots"
        SENT      = "sent",      "Nosūtīts parakstīšanai"
        SIGNED    = "signed",    "Parakstīts"
        VOID      = "void",      "Atcelts"

    class SigningPath(models.TextChoices):
        ELECTRONIC = "electronic", "Elektroniski"
        PAPER      = "paper",      "Ar roku, papīra dokuments"

    member = models.OneToOneField(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="agreement",
    )
    state = models.CharField(max_length=16, choices=State.choices, default=State.GENERATED)
    signing_path = models.CharField(
        max_length=16,
        choices=SigningPath.choices,
        default=SigningPath.ELECTRONIC,
    )

    # Lifecycle timestamps
    generated_at = models.DateTimeField()              # set at create
    sent_at      = models.DateTimeField(null=True, blank=True)
    signed_at    = models.DateTimeField(null=True, blank=True)
    voided_at    = models.DateTimeField(null=True, blank=True)
    void_reason  = models.TextField(blank=True, default="")

    # Slice D reservations — populated by Slice D, ignored in Slice C
    external_provider = models.CharField(max_length=32, blank=True, default="")
    external_id       = models.CharField(max_length=128, blank=True, default="")
    external_state    = models.CharField(max_length=64, blank=True, default="")
    external_url      = models.URLField(blank=True, default="")
```

`TimeStampedModel` (from `apps/core/models.py`) provides `created_at` / `updated_at`. One migration (`0001_initial.py`).

### Services — `apps/agreements/services.py`

```python
def create_agreement_for_member(member, signing_path) -> Agreement:
    """Idempotent: return existing Agreement if one already exists for this
    Member; otherwise create with state=generated, generated_at=now()."""

def mark_agreement_sent(agreement, actor) -> Agreement:
    """generated → sent. Sets sent_at, sends Latvian email to guardian."""

def mark_agreement_signed(agreement, actor) -> Agreement:
    """{generated, sent} → signed. Sets signed_at, sends Latvian confirmation
    email. The direct generated → signed path supports the 'I already have
    the signed paper in hand' staff flow."""

def void_agreement(agreement, actor, reason) -> Agreement:
    """Any non-void state → void. Sets voided_at and void_reason. No email.
    Idempotent on void → void (no-op)."""

def set_signing_path(agreement, path, actor) -> Agreement:
    """Change signing_path at any state. No email. Idempotent on same-value."""
```

Each transition raises `ValueError` for illegal source states (e.g. `mark_agreement_sent` on a `signed` agreement). `actor` is plumbed-but-unused — same convention as `assign_training_group` and `_send_notification` for the P7 audit hook.

### Approval integration — `apps/registrations/services.py::approve_application`

One line added inside the existing atomic block, after `Member.objects.create(...)`:

```python
from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member

create_agreement_for_member(
    member,
    signing_path=application.preferred_agreement_signing or Agreement.SigningPath.ELECTRONIC,
)
```

Idempotency rule unchanged: `approve_application` returns early when `approved_member_id` is set. The inner `create_agreement_for_member` is itself idempotent — so even if approval is called twice on a legacy record without an agreement, a second call creates exactly one agreement.

### View extensions — `apps/registrations/views.py::admin_review_detail`

- Context entries (post-approval only): `agreement` (the Member's agreement instance, or `None`).
- Four new POST `action` branches:
  - `action == "mark_agreement_sent"` → call service; redirect back. ValueError → 400 + Latvian copy.
  - `action == "mark_agreement_signed"` → same shape.
  - `action == "set_signing_path"` → reads `signing_path` POST value; validates against `Agreement.SigningPath.values`; calls service; redirect.
  - `action == "void_agreement"` → reads `void_reason` POST value; calls service; redirect.
- All four guarded by `agreement is not None` (return 400 + "Līgums nav sagatavots." for the safety case).

### Template — `templates/registrations/admin_review_detail.html`

A new module rendered after the Treniņu grupa module, only when `application.approved_member` exists. Shape (Latvian copy in spec, structure in pseudocode):

```html
{% if agreement %}
<div class="module mms-review-agreement-module">
  <h2>Līgums</h2>
  <p>Stāvoklis: <strong>{{ agreement.get_state_display }}</strong></p>

  <form method="post" class="mms-review-actions__form">
    {% csrf_token %}
    <label for="signing_path">Parakstīšanas veids:</label>
    <select name="signing_path" id="signing_path">
      <option value="electronic" {% if agreement.signing_path == "electronic" %}selected{% endif %}>Elektroniski</option>
      <option value="paper"      {% if agreement.signing_path == "paper" %}selected{% endif %}>Ar roku, papīra dokuments</option>
    </select>
    <button type="submit" name="action" value="set_signing_path">Saglabāt</button>
  </form>

  <p>Sagatavots: {{ agreement.generated_at|date:"d.m.Y H:i" }}</p>
  {% if agreement.sent_at %}<p>Nosūtīts: {{ agreement.sent_at|date:"d.m.Y H:i" }}</p>{% endif %}
  {% if agreement.signed_at %}<p>Parakstīts: {{ agreement.signed_at|date:"d.m.Y H:i" }}</p>{% endif %}
  {% if agreement.voided_at %}<p>Atcelts: {{ agreement.voided_at|date:"d.m.Y H:i" }} — {{ agreement.void_reason }}</p>{% endif %}

  {% if agreement.state == "generated" %}
  <form method="post"><button name="action" value="mark_agreement_sent">Atzīmēt kā nosūtītu</button></form>
  {% endif %}

  {% if agreement.state == "generated" or agreement.state == "sent" %}
  <form method="post"><button name="action" value="mark_agreement_signed">Atzīmēt kā parakstītu</button></form>
  {% endif %}

  {% if agreement.state != "void" %}
  <details class="mms-review-actions__disclosure">
    <summary>Atcelt līgumu</summary>
    <form method="post">
      <label for="void_reason">Iemesls:</label>
      <textarea name="void_reason" id="void_reason" rows="3"></textarea>
      <button name="action" value="void_agreement">Atcelt</button>
    </form>
  </details>
  {% endif %}
</div>
{% endif %}
```

CSS additions in `static/admin/css/review.css` are small — `.mms-review-agreement-module` rules for spacing rhythm, no new tokens.

### Parent visibility

**Parent portal `/portal/`** — each approved-application card gains an agreement-status line below the existing approval state. Latvian copy chosen per `(state, signing_path)`:

| state | signing_path | parent-facing copy |
|---|---|---|
| generated | (either) | "Līgums sagatavots, drīzumā saņemsiet to parakstīšanai." |
| sent | electronic | "Līgums nosūtīts uz e-pastu parakstīšanai." |
| sent | paper | "Klubs sazināsies ar Jums par līguma parakstīšanu." |
| signed | (either) | "Līgums parakstīts ✓" |
| void | (either) | "Līgums atcelts." |

**Workspace `/applications/<id>/`** (read-only post-approval render) — same status text inline near the existing application-status banner.

A small template helper `agreement_status_copy(agreement)` lives in `apps/agreements/presentation.py` and returns the Latvian string for the `(state, signing_path)` pair. Both the portal and the workspace render the result of this single helper, so there's no copy duplication between templates.

No PDF download or preview anywhere. DocuSeal owns the document in Slice D; paper-path documents live outside the app.

### Emails — `templates/emails/agreements/`

Two new plain-text templates following the Slice A.1 pattern.

**`sent.txt`:**
```
Sveiki, {{ guardian_full_name }}!

Jūsu bērna {{ member_full_name }} līgums ir nosūtīts parakstīšanai.

{% if signing_path == "electronic" %}Lūdzu, parakstiet to elektroniski pēc instrukcijām, ko saņemsiet atsevišķā e-pastā.{% else %}Klubs sazināsies ar Jums par līguma fizisko parakstīšanu.{% endif %}

Statuss redzams portālā:
{{ portal_url }}

FK Cēsis
```

**`signed.txt`:**
```
Sveiki, {{ guardian_full_name }}!

Apstiprinām, ka {{ member_full_name }} līgums ir parakstīts.

Paldies par sadarbību. Tālāk sagaidiet informāciju par maksājumiem un treniņu kalendāru.

{{ portal_url }}

FK Cēsis
```

Context built by a new helper in `apps/agreements/services.py` that mirrors `_render_and_send_notification` (Slice A.1) — same `render_to_string` + `send_mail` pattern. Recipient: `agreement.member.guardian.email`.

## Tests

Three new test files in `tests/agreements/`, two in `tests/registrations/`:

### `tests/agreements/test_agreement_model.py`
- Defaults: new Agreement has `state=generated`, `signing_path=electronic`, `generated_at` non-null.
- OneToOne constraint: creating a second Agreement for the same Member raises `IntegrityError`.
- State + SigningPath choice lists match the spec.
- `member` cascade delete: deleting the Member deletes the Agreement.

### `tests/agreements/test_agreement_services.py`
- `create_agreement_for_member`: creates on first call; second call returns the same instance (no second row).
- `mark_agreement_sent` from `generated` → succeeds, sets `sent_at`, sends one email to the guardian.
- `mark_agreement_sent` from `sent` / `signed` / `void` → `ValueError`.
- `mark_agreement_signed` from `generated` and from `sent` → both succeed, set `signed_at`, send email.
- `mark_agreement_signed` from `signed` / `void` → `ValueError`.
- `void_agreement` from any non-void state → succeeds, sets `voided_at` + `void_reason`, no email.
- `void_agreement` from `void` → idempotent no-op (no UPDATE — `CaptureQueriesContext` proof).
- `set_signing_path`: changes path, no email, idempotent on same value.
- Each email-sending transition: subject is Latvian, body contains the portal URL, recipient is `agreement.member.guardian.email`.

### `tests/registrations/test_admin_review_agreement_ui.py`
- Post-approval review detail shows the Līgums module with the correct state copy.
- `mark_agreement_sent` POST advances state, refreshes the page, no longer offers the "Atzīmēt kā nosūtītu" button.
- `mark_agreement_signed` POST works from both `generated` and `sent`.
- `set_signing_path` POST flips `electronic ⇄ paper` regardless of state.
- `void_agreement` POST with a reason transitions to void.
- POST without an agreement (e.g. submitted-status application) → 400 + Latvian error.
- ValueError from a service (illegal transition forced via direct DB edit + POST) → 400 + Latvian error.
- Anonymous POST → blocked (302/404 like the rest).

### `tests/registrations/test_agreement_visibility_parent_surfaces.py`
- Portal: approved application with `agreement.state=generated` shows the Latvian "Līgums sagatavots…" line.
- Portal: each (state, signing_path) pair from the table renders its mapped copy.
- Workspace: post-approval workspace shows the same status copy.
- Pre-approval surfaces (draft, submitted) don't show any agreement copy.

### `tests/registrations/test_admin_approval_with_group.py` (extend)
- `approve_application` without `training_group` now also creates an Agreement linked to the new Member with `signing_path` defaulting to `electronic` when the application's `preferred_agreement_signing` is empty.
- When the application has `preferred_agreement_signing="paper"`, the Agreement's `signing_path` is `"paper"`.
- Idempotent re-approval does NOT create a second Agreement (covered by `create_agreement_for_member` test, but worth a regression at the integration level).

Expected new test count: ~25–30. Suite target ≈ 940 from the 913 baseline.

## Files

**Create:**
- `apps/agreements/__init__.py`
- `apps/agreements/apps.py`
- `apps/agreements/models.py`
- `apps/agreements/services.py`
- `apps/agreements/presentation.py` (the `agreement_status_copy` helper)
- `apps/agreements/admin.py` (minimal `AgreementAdmin` — read-only listing in Django admin)
- `apps/agreements/migrations/__init__.py`
- `apps/agreements/migrations/0001_initial.py`
- `templates/emails/agreements/sent.txt`
- `templates/emails/agreements/signed.txt`
- `tests/agreements/__init__.py`
- `tests/agreements/conftest.py`
- `tests/agreements/test_agreement_model.py`
- `tests/agreements/test_agreement_services.py`
- `tests/registrations/test_admin_review_agreement_ui.py`
- `tests/registrations/test_agreement_visibility_parent_surfaces.py`

**Modify:**
- `fk_cesis_mms/settings.py` (`INSTALLED_APPS += ["apps.agreements"]`)
- `apps/registrations/services.py` (`approve_application` calls `create_agreement_for_member`)
- `apps/registrations/views.py` (`admin_review_detail` context + four POST branches)
- `templates/registrations/admin_review_detail.html` (Līgums module)
- `templates/registrations/parent_portal.html` (status line per card)
- The post-approval workspace template (status line near the application-status banner)
- `static/admin/css/review.css` (small `.mms-review-agreement-module` additions)
- `tests/registrations/test_admin_approval_with_group.py` (extend with 3 agreement-integration tests)

**NOT touched:**
- `apps/accounts/*`
- `apps/documents/*`
- `apps/billing/*` (Slice C does not advance billing — that's P6)
- Parent registration surfaces pre-approval
- `apps/integrations/*` (DocuSeal lives there in Slice D)
- Any model in another app

## Out of scope (explicit)

- DocuSeal self-hosted adapter / external API call / submission creation / signed-state webhook — Slice D.
- Email suppression for the electronic signing path — Slice D.
- PDF storage or in-app preview of the signed agreement document.
- Regenerating an Agreement after `void` (terminal in Slice C).
- Audit-log entries for state transitions (P7 target).
- Email notifications on `generated` and `void`.
- Bulk admin actions across many agreements at once.
- Billing-trigger wiring (P6 — depends on `signed` state but is not implemented here).
- Migration of any pre-Slice-C Members to back-fill Agreements (test fixtures handle their own; production has none today).

## Verification

1. `uv run pytest -q` → ≥ 940 passing.
2. `uv run ruff check .` and `uv run mypy .` clean.
3. Manual LAN check at `http://192.168.3.245:8000/admin/review/applications/<id>/`:
   - Approve a fresh application → the Līgums module appears with state `Sagatavots` and signing path defaulting to `Elektroniski` (or matching the application's preference).
   - Mark sent → state updates, parent receives `sent.txt`, the "Atzīmēt kā nosūtītu" button disappears.
   - Mark signed → state updates, parent receives `signed.txt`, the "Atzīmēt kā parakstītu" button disappears.
   - Flip `signing_path` while signed → succeeds, no email, state copy reflects the new path.
   - Void with a reason → state updates, no email, all transition buttons gone, reason rendered with the timestamp.
   - Open `/portal/` as the parent — agreement-status line appears under the application card and matches the table copy for each `(state, signing_path)` pair walked through.
   - Confirm idempotent re-approval (manual: mark status back to `submitted` via Django admin, re-POST `approve`) doesn't create a second agreement.
4. Update `AGENTS.md` (Current Status + new "P5 Slice C delivered" entry) and `docs/milestones.md` (mark Slice C delivered under the P5 status block).
