# Address Autocomplete Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local VZD address autocomplete include villages/locality-level addresses and find building addresses when users type house numbers in either natural order.

**Architecture:** Keep the existing `apps.addresses` app and current database schema. Extend import logic to attach `AW_EKA` rows whose parent is a locality (not a street) to locality groups, extend search ranking to include building entries for number-bearing queries, and adjust the widget to send only the typed suffix after a selected group label.

**Tech Stack:** Python 3.12, Django 5, Django ORM, SQLite/PostgreSQL-compatible queries, vanilla JavaScript, pytest/pytest-django, uv, ruff, mypy.

---

## Source Documents

- Design spec: `docs/superpowers/specs/2026-06-27-address-autocomplete-design.md`
- Current implementation: `apps/addresses/services.py`
- Current endpoint: `apps/addresses/views.py`
- Current widget: `static/js/address_autocomplete.js`
- Current tests: `tests/addresses/test_import_addresses.py`, `tests/addresses/test_search.py`, `tests/addresses/test_autocomplete_view.py`

---

## 1. Design Decisions

### 1.1 Import locality-level addresses without schema changes

**Decision:** Reuse `AddressGroup` for non-street localities.

- Street-backed group example: `Raiņa iela, Cēsis`.
- Locality-backed group example: `Priekuļi, Priekuļu pag.`.
- Locality-backed groups have `street_code=""` and `street_name=""`; `locality_code`, `locality_name`, `region_code`, and `region_name` are filled.

**Why:** Existing models already represent a display group plus child `AddressEntry` rows. Adding a new model or nullable group type enum is unnecessary for this behavior.

### 1.2 Resolve full VZD locality hierarchy

**Decision:** Build a `locality_map` for active `AW_PILSETA`, `AW_PAGASTS`, and `AW_CIEMS` rows. Each map item stores:

- `name`
- `region_code`
- `parent_code`
- `parent_name`
- `kind` (`city`, `parish`, `village`)

For villages, `parent_name` is usually the parish name. For cities under a novads or state cities, `parent_name` can be blank.

**Why:** Village display needs enough hierarchy to show `Priekuļi, Priekuļu pag.` while still filtering by `Cēsu nov.`. This stays in import code and avoids persisted extra fields.

### 1.3 Search entries only when useful

**Decision:** If query contains a number-like token (`12`, `12A`, `12-1`), search `AddressEntry` rows as well as groups. If query has no number token, keep group-first behavior.

**Why:** Users typing only `Raiņa` should not get spammed with every house number. Users typing `Raiņa iela 12` or `12 Raiņa iela` clearly want a building.

### 1.4 Token matching over substring matching for building search

**Decision:** For entry search, normalize query and require every token to appear in `AddressEntry.normalized_label`, regardless of order. Rank entries with labels starting with the normalized query first, then entries containing the house token near the street/locality tokens.

**Why:** SQLite and PostgreSQL both support this with chained `icontains` filters. No trigram extension, no new dependency, no provider.

### 1.5 Selected-group suffix query

**Decision:** In `static/js/address_autocomplete.js`, when an input has `data-address-group-id` and current value starts with the selected group label, send only the suffix after the selected group label as `q`. Example:

- visible input: `Raiņa iela, Cēsis 12`
- request: `/addresses/autocomplete/?q=12&group=<id>`

If suffix is empty, send the full group label or keep current behavior to list buildings.

**Why:** The existing server-side group filter searches entry labels. Entry labels do not contain the exact comma-separated group text at the beginning in every useful way, so sending only `12` makes narrowing reliable.

---

## 2. File-by-File Plan

### Modify `apps/addresses/services.py`

Add helpers:

```python
def _has_house_token(normalized: str) -> bool:
    return any(re.search(r"\d", token) for token in normalized.split())
```

```python
def _entry_results(filters: Q, normalized: str, limit: int) -> list[dict[str, str]]:
    token_filters = filters
    for token in normalized.split():
        token_filters &= Q(normalized_label__icontains=token)
    qs = (
        AddressEntry.objects.filter(token_filters)
        .annotate(
            rank=Case(
                When(normalized_label__startswith=normalized, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("rank", "normalized_label")
        .values("id", "label", "postal_code", "region_name")[:limit]
    )
    return [
        {"kind": "address", "id": str(row["id"]), "label": row["label"], "hint": row["postal_code"] or row["region_name"] or ""}
        for row in qs
    ]
```

Change import logic:

- Build explicit maps for novads, parishes, cities, villages.
- Let `AW_EKA.VKUR_CD` resolve either:
  - to `iela_map` (street path), or
  - to `locality_map` (locality path).
- For locality path, create group label from locality plus parent parish when present.

Change `search_addresses()`:

- For `group_id is not None`, call `_entry_results(Q(group_id=group_id), normalized, limit)`.
- For no group and house token present, return entry results first, then group results to fill remaining slots.
- For no group and no house token, keep group-only behavior.

### Modify `static/js/address_autocomplete.js`

Add helper:

```javascript
function getQuery(input) {
  var value = input.value.trim();
  var groupLabel = input.getAttribute("data-address-group-label") || "";
  if (getGroupId(input) && groupLabel && value.indexOf(groupLabel) === 0) {
    var suffix = value.slice(groupLabel.length).replace(/^\s*,?\s*/, "").trim();
    return suffix || groupLabel;
  }
  return value;
}
```

Use `getQuery(input)` inside `fetchSuggestions()` for endpoint `q`, while still using `input.value` for display.

### Modify `tests/addresses/test_import_addresses.py`

Add tests for locality parent import:

```python
@pytest.mark.django_db
def test_import_vzd_addresses_creates_locality_group_for_non_street_parent(tmp_path):
    files = make_vzd_files_with_priekuli_locality_parent(tmp_path)

    run = import_vzd_addresses(files, region_codes=["300"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    group = AddressGroup.objects.get()
    assert group.label == "Priekuļi, Priekuļu pag."
    assert group.street_code == ""
    assert group.locality_name == "Priekuļi"
    assert AddressEntry.objects.get().label == "Saules 1, Priekuļi, Priekuļu pag., Cēsu nov."
```

Use local fixture rows:

- `AW_NOVADS`: `300,EKS,Cēsu nov.,`
- `AW_PAGASTS`: `250,EKS,Priekuļu pag.,300`
- `AW_CIEMS`: `240,EKS,Priekuļi,250`
- `AW_IELA`: empty
- `AW_EKA`: `501,EKS,240,Saules 1,"Saules 1, Priekuļi, Priekuļu pag., Cēsu nov.",LV-4126,,,,`

### Modify `tests/addresses/test_search.py`

Add tests:

```python
@pytest.mark.django_db
def test_search_returns_entry_for_street_then_house_number(raina_group):
    results = search_addresses("Raiņa iela 12")
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov."
```

```python
@pytest.mark.django_db
def test_search_returns_entry_for_house_number_then_street(raina_group):
    results = search_addresses("12 Raiņa iela")
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov."
```

```python
@pytest.mark.django_db
def test_search_selected_group_accepts_house_number_only(raina_group):
    results = search_addresses("12", group_id=raina_group.id)
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov."
```

Adjust `raina_group` fixture to include `Raiņa iela 12, Cēsis, Cēsu nov.`.

### Modify `tests/addresses/test_autocomplete_view.py`

Add endpoint-level coverage:

```python
@pytest.mark.django_db
def test_autocomplete_supports_group_house_number_suffix(verified_client):
    group = AddressGroup.objects.create(...)
    AddressEntry.objects.create(label="Raiņa iela 12, Cēsis, Cēsu nov.", normalized_label="raina iela 12 cesis cesu nov", group=group, ...)

    response = verified_client.get(reverse("addresses:autocomplete"), {"q": "12", "group": str(group.id)})

    assert response.status_code == 200
    assert response.json()["results"][0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov."
```

### Add `tests/registrations/test_address_autocomplete_js.py` or extend hook tests

Keep simple static contract test, no browser runner:

```python
def test_address_autocomplete_js_sends_suffix_after_selected_group():
    source = Path("static/js/address_autocomplete.js").read_text()

    assert "function getQuery" in source
    assert "data-address-group-label" in source
    assert "slice(groupLabel.length)" in source
```

This is not a full JS test, but it catches regression of the specific no-build JS contract in this repo.

### Update `docs/address-autocomplete.md`

Add operator note:

- Current import includes active `AW_EKA` rows under streets and localities.
- Apartments/units from `AW_DZIV` remain out of scope.
- Recommended manual smoke checks after import:
  - `Priekuļi`
  - `Raiņa iela 12`
  - `12 Raiņa iela`

---

## 3. Test Strategy

### What to test

- Import includes locality-level `AW_EKA` rows with no street parent.
- Import still includes street-backed rows.
- Region filter still excludes rows outside configured region.
- `Priekuļi` finds a locality group.
- `Raiņa iela 12` finds the building entry.
- `12 Raiņa iela` finds the same building entry.
- `group=<id>&q=12` finds building entries inside the selected group.
- JS sends suffix query after selected group label.

### What not to test

- `AW_DZIV` apartment rows; explicitly out of scope.
- Browser pixel/UI layout; current static contract tests are enough.
- PostgreSQL trigram/performance; not used.
- Hard validation of manually typed addresses; not part of feature.

### Verification commands

Run after implementation:

```bash
uv run pytest tests/addresses tests/registrations/test_address_autocomplete_hooks.py tests/registrations/test_address_autocomplete_css.py -q
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

After local VZD files are available, reimport and smoke via shell:

```bash
uv run python manage.py import_addresses --novads /tmp/opencode/vzd-addresses/AW_NOVADS.CSV --pagasts /tmp/opencode/vzd-addresses/AW_PAGASTS.CSV --pilseta /tmp/opencode/vzd-addresses/AW_PILSETA.CSV --ciems /tmp/opencode/vzd-addresses/AW_CIEMS.CSV --iela /tmp/opencode/vzd-addresses/AW_IELA.CSV --eka /tmp/opencode/vzd-addresses/AW_EKA.CSV --region-code 100016487
uv run python manage.py shell -c "from apps.addresses.services import search_addresses; print(search_addresses('Priekuļi')[:3]); print(search_addresses('Raiņa iela 12')[:3]); print(search_addresses('12 Raiņa iela')[:3])"
```

---

## 4. Acceptance Criteria Per Unit

### Import unit

- `import_vzd_addresses()` imports street-backed `AW_EKA` rows unchanged.
- `import_vzd_addresses()` imports locality-backed `AW_EKA` rows.
- Locality-backed group label for Priekuļi is `Priekuļi, Priekuļu pag.`.
- Imported entry count includes both street-backed and locality-backed active rows.
- No model migration is generated.

### Search unit

- Query with no number token returns group-first results.
- Query with number token returns address entries before unrelated group-only results.
- Token order does not matter for building entry lookup.
- Selected-group search accepts a number-only query.

### Endpoint unit

- `/addresses/autocomplete/?q=12&group=<id>` returns building suggestions for authenticated parent session.
- Endpoint result shape remains `{"results": [...]}`.
- Unauthenticated behavior remains unchanged.

### JS/UI unit

- Manual typing still works if no suggestion is selected.
- Selecting a group keeps group metadata on the input.
- Typing a suffix after a selected group sends suffix query to the endpoint.
- Selecting a building replaces the full input value with official address text.

### Docs unit

- Operator docs describe locality import and no-apartment scope.
- Smoke-check examples include `Priekuļi`, `Raiņa iela 12`, and `12 Raiņa iela`.

---

## 5. Task Breakdown

### Task 1: Import locality-level addresses

**Files:**

- Modify: `apps/addresses/services.py`
- Modify: `tests/addresses/test_import_addresses.py`

- [ ] **Step 1: Write failing import test**

Add `test_import_vzd_addresses_creates_locality_group_for_non_street_parent` to `tests/addresses/test_import_addresses.py` using the fixture rows described above.

- [ ] **Step 2: Run RED test**

```bash
uv run pytest tests/addresses/test_import_addresses.py::test_import_vzd_addresses_creates_locality_group_for_non_street_parent -q
```

Expected: FAIL because current importer skips `AW_EKA` rows whose `VKUR_CD` is not a street code.

- [ ] **Step 3: Implement minimal import fix**

In `apps/addresses/services.py`, extend hierarchy mapping so `row["VKUR_CD"]` can resolve to street or locality. Keep existing street path intact.

- [ ] **Step 4: Run import tests**

```bash
uv run pytest tests/addresses/test_import_addresses.py -q
```

Expected: PASS.

### Task 2: Building-number search

**Files:**

- Modify: `apps/addresses/services.py`
- Modify: `tests/addresses/test_search.py`
- Modify: `tests/addresses/test_autocomplete_view.py`

- [ ] **Step 1: Write failing search tests**

Add tests for:

- `search_addresses("Raiņa iela 12")`
- `search_addresses("12 Raiņa iela")`
- `search_addresses("12", group_id=raina_group.id)`

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/addresses/test_search.py -q
```

Expected: FAIL because no-group search currently returns groups only, and group search rejects 2-character `12`.

- [ ] **Step 3: Implement minimal search fix**

Add `_has_house_token()`, `_entry_results()`, and update `search_addresses()` as described in the file-by-file plan.

- [ ] **Step 4: Add endpoint regression test**

Add endpoint test for `q=12&group=<id>`.

- [ ] **Step 5: Run address tests**

```bash
uv run pytest tests/addresses -q
```

Expected: PASS.

### Task 3: Selected-group suffix query in JS

**Files:**

- Modify: `static/js/address_autocomplete.js`
- Modify: `tests/registrations/test_address_autocomplete_hooks.py` or create `tests/registrations/test_address_autocomplete_js.py`

- [ ] **Step 1: Add static JS contract test**

Assert `address_autocomplete.js` contains `function getQuery`, reads `data-address-group-label`, and slices `groupLabel.length`.

- [ ] **Step 2: Run RED test**

```bash
uv run pytest tests/registrations/test_address_autocomplete_js.py -q
```

Expected: FAIL until helper is added.

- [ ] **Step 3: Implement `getQuery(input)`**

Use the helper shown in the file-by-file plan. Use its return value for endpoint `q` in `fetchSuggestions()`.

- [ ] **Step 4: Run registration address tests**

```bash
uv run pytest tests/registrations/test_address_autocomplete_hooks.py tests/registrations/test_address_autocomplete_css.py tests/registrations/test_address_autocomplete_js.py -q
```

Expected: PASS.

### Task 4: Docs and full verification

**Files:**

- Modify: `docs/address-autocomplete.md`

- [ ] **Step 1: Update docs**

Add locality-level import note, no-`AW_DZIV` reminder, and three smoke-check examples.

- [ ] **Step 2: Run full verification**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected:

- pytest passes
- ruff passes
- mypy passes
- makemigrations reports no changes

- [ ] **Step 3: Reimport local data and smoke test**

Run import command against `/tmp/opencode/vzd-addresses/` and smoke-check:

- `Priekuļi`
- `Raiņa iela 12`
- `12 Raiņa iela`

Expected: all return useful suggestions.

---

## 6. Documentation Scope

Update only `docs/address-autocomplete.md`. Do not change broad milestone docs unless implementation reveals a new operational constraint.

---

## 7. Plan Self-Review

- Spec coverage: locality/village search, building-number order-insensitive search, selected group suffix query, no apartments, no VZD code persistence, manual fallback all mapped to tasks.
- Placeholder scan: no `TBD`, no unspecified implementation steps, no new future scaffolding.
- Type consistency: functions use existing `search_addresses(query: str, group_id: int | None = None, limit: int = 10)` API; no endpoint shape change.
- Scope check: one bounded refinement to existing address autocomplete; no decomposition needed.
