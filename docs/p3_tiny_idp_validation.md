# P3 tiny-IDP live validation evidence

Provider host: `api.tiny-idp.com`
Negative-case (bad token) outcome: `provider_unavailable`

Samples processed: 3

## Sample 1: `63653b5ce54b` (guardian_identity)

- expected kind: ``
- provider kind: `—`
- latency: 9609 ms

| Field | Outcome | Raw path (if dropped by normalizer) |
|---|---|---|
| `date_of_birth` | `hit` | — |
| `document_number` | `missing_everywhere` | — |
| `expiry_date` | `hit` | — |
| `first_name` | `hit` | — |
| `last_name` | `hit` | — |
| `personal_id` | `hit` | — |

## Sample 2: `8537116a2095` (guardian_identity)

- expected kind: ``
- provider kind: `—`
- latency: 8566 ms

| Field | Outcome | Raw path (if dropped by normalizer) |
|---|---|---|
| `date_of_birth` | `hit` | — |
| `document_number` | `hit` | — |
| `expiry_date` | `missing_everywhere` | — |
| `first_name` | `hit` | — |
| `last_name` | `miss` | — |
| `personal_id` | `hit` | — |

## Sample 3: `98c3c2bdf895` (member_identity)

- expected kind: ``
- provider kind: `—`
- latency: 4182 ms

| Field | Outcome | Raw path (if dropped by normalizer) |
|---|---|---|
| `date_of_birth` | `missing_everywhere` | — |
| `document_number` | `hit` | — |
| `expiry_date` | `missing_everywhere` | — |
| `first_name` | `missing_everywhere` | — |
| `last_name` | `missing_everywhere` | — |
| `personal_id` | `missing_everywhere` | — |

