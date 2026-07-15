# Family Hub Action Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return staff to the acted-on child card after every child-specific family-hub action.

**Architecture:** `build_family_hub_context()` assigns every child a stable DOM anchor based on its source application, falling back to its Member only when no source application exists. The template sends that anchor with each child control, and `GuardianAdmin` appends only allowlisted local fragments to its existing hub redirects. This retains server-rendered, no-JavaScript behavior and changes no workflow logic.

**Tech Stack:** Python 3.12, Django admin/templates, pytest-django.

---

## File structure

- `apps/members/family_hub.py` — child context shape and stable anchor contract.
- `apps/members/admin.py` — validate posted/query anchor and build anchored hub redirects.
- `templates/admin/members/guardian/family_hub.html` — child DOM ids and return-anchor form/query fields.
- `tests/admin_hub/test_family_hub_page.py` — rendered-anchor contract.
- `tests/admin_hub/test_family_hub_actions.py` — redirect and invalid-input contracts.

No migration, CSS, JavaScript, service, or operator-guide change is needed.

### Task 1: Write red redirect and rendering tests

**Files:**
- Modify: `tests/admin_hub/test_family_hub_page.py`
- Modify: `tests/admin_hub/test_family_hub_actions.py`

- [ ] **Step 1: Add rendered-card anchor test**

Add this test to `tests/admin_hub/test_family_hub_page.py`:

```python
def test_hub_renders_application_child_anchor_and_return_field(
    staff_client, submitted_application,
):
    response = staff_client.get(_hub_url(submitted_application.guardian))

    anchor = f"child-application-{submitted_application.pk}"
    html = response.content.decode()

    assert f'id="{anchor}"' in html
    assert f'name="return_anchor" value="{anchor}"' in html
```

- [ ] **Step 2: Add action redirect tests**

Add tests to `tests/admin_hub/test_family_hub_actions.py` using the existing
`_action_url()` and fixture setup:

```python
def test_approve_application_redirects_to_its_application_anchor(
    staff_client, submitted_application,
):
    anchor = f"child-application-{submitted_application.pk}"
    response = staff_client.post(
        _action_url(submitted_application.guardian),
        {
            "action": "approve_application",
            "application_id": submitted_application.pk,
            "return_anchor": anchor,
        },
    )

    assert response["Location"] == f"{_hub_url(submitted_application.guardian)}#{anchor}"
```

Add equivalent assertions for an existing agreement action, the inline
training-group action, and billing confirmation. For those Member-backed
controls, post `return_anchor=f"child-application-{approved_application.pk}"`
and assert that exact fragment. This pins the source-application anchor after
approval.

Add invalid and missing-input coverage:

```python
def test_hub_action_discards_invalid_return_anchor(staff_client, submitted_application):
    response = staff_client.post(
        _action_url(submitted_application.guardian),
        {
            "action": "request_fix",
            "application_id": submitted_application.pk,
            "review_message": "Lūdzu papildiniet.",
            "return_anchor": "https://attacker.example/#x",
        },
    )

    assert response["Location"] == _hub_url(submitted_application.guardian)
```

Extend the existing no-external-id DocuSeal test to request
`?return_anchor=child-application-<pk>` without `follow=True`, then assert the
anchored hub `Location`.

- [ ] **Step 3: Run the targeted tests and confirm red phase**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_page.py tests/admin_hub/test_family_hub_actions.py -q
```

Expected: new anchor assertions fail because cards have no `id`, forms do not
submit `return_anchor`, and redirects have no fragment.

### Task 2: Add stable child anchors and anchored redirects

**Files:**
- Modify: `apps/members/family_hub.py`
- Modify: `apps/members/admin.py`
- Modify: `templates/admin/members/guardian/family_hub.html`

- [ ] **Step 1: Extend child context**

In `apps/members/family_hub.py`:

1. Add `anchor_id: str` to `_Child`.
2. Add a private helper near the context builders:

```python
def _child_anchor_id(application, member) -> str:
    if application is not None:
        return f"child-application-{application.pk}"
    return f"child-member-{member.pk}"
```

3. Set `"anchor_id": _child_anchor_id(application, member)` in both child
   dictionaries built by `build_family_hub_context()`. The pending-application
   branch passes its application and `None`; the Member branch passes both its
   source application and Member.

This makes the application anchor stable before and after approval.

- [ ] **Step 2: Render and send anchors**

In `templates/admin/members/guardian/family_hub.html`:

1. Change the outer child-card element to:

```django
<div class="module" id="{{ child.anchor_id }}">
```

2. In every child `<form method="post" action="{{ action_url }}">`, immediately
   after `{% csrf_token %}`, add:

```django
<input type="hidden" name="return_anchor" value="{{ child.anchor_id }}">
```

This includes application, agreement, membership, and billing forms.

3. Change the DocuSeal PDF link to include:

```django
?return_anchor={{ child.anchor_id }}
```

after its existing URL tag.

- [ ] **Step 3: Restrict and preserve redirect fragment**

In `apps/members/admin.py`:

1. Import `re` and define a module-level compiled expression:

```python
_FAMILY_HUB_ANCHOR_RE = re.compile(r"child-(?:application|member)-\d+")
```

2. Change `_family_hub_redirect` to accept `return_anchor: str = ""`, reverse
   the current hub URL, and append `#{return_anchor}` only when
   `_FAMILY_HUB_ANCHOR_RE.fullmatch(return_anchor)` succeeds.

3. In `family_hub_action_view`, read `return_anchor = request.POST.get(
   "return_anchor", "")` after the Guardian lookup and pass it to every
   post-handler redirect path, including unknown-action and caught-error paths.
   The initial non-POST redirect remains unanchored.

4. In `family_hub_docuseal_document_view`, read
   `return_anchor = request.GET.get("return_anchor", "")` and pass it to every
   fallback hub redirect. Leave successful external PDF redirects unchanged.

No handler changes object lookup or authorization. The anchor is only a local
fragment after the already-authorized request completes.

- [ ] **Step 4: Run targeted tests and confirm green phase**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_page.py tests/admin_hub/test_family_hub_actions.py -q
```

Expected: all tests pass.

### Task 3: Verify regression boundaries

**Files:**
- Modify: none

- [ ] **Step 1: Run focused static and migration checks**

Run:

```bash
uv run ruff check apps/members tests/admin_hub
uv run mypy apps/members
uv run python manage.py makemigrations --check
```

Expected: all commands succeed; no migration is generated.

- [ ] **Step 2: Run repository verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected: full suite and static checks succeed, with no schema drift.

## Plan self-review

- **Spec coverage:** all child POST controls, approval stability, PDF fallback,
  invalid input, and unchanged workflows map to Tasks 1–3.
- **No placeholders:** paths, names, fields, tests, and commands are explicit.
- **Consistency:** template field is `return_anchor`; context field is
  `anchor_id`; accepted fragments use `child-application-<pk>` or
  `child-member-<pk>` throughout.
