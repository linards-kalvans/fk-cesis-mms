# P3 tiny-IDP live validation evidence

Provider host: `api.tiny-idp.com`
Negative-case (bad token) outcome: `provider_unavailable`

Samples processed: 3

## Sample 1: `63653b5ce54b` (guardian_identity)

- expected kind: `id_card`
- provider kind: `—`
- latency: 6663 ms

| Field | Outcome | Raw path (if dropped by normalizer) |
|---|---|---|
| `date_of_birth` | `hit` | — |
| `document_number` | `hit` | — |
| `expiry_date` | `hit` | — |
| `first_name` | `hit` | — |
| `last_name` | `miss` | — |
| `personal_id` | `hit` | — |

## Sample 2: `8537116a2095` (guardian_identity)

- expected kind: `passport`
- provider kind: `—`
- latency: 6909 ms

| Field | Outcome | Raw path (if dropped by normalizer) |
|---|---|---|
| `date_of_birth` | `hit` | — |
| `document_number` | `hit` | — |
| `expiry_date` | `hit` | — |
| `first_name` | `hit` | — |
| `last_name` | `miss` | — |
| `personal_id` | `hit` | — |

## Sample 3: `98c3c2bdf895` (member_identity)

- expected kind: `id_card`
- provider kind: `—`
- latency: 2190 ms

| Field | Outcome | Raw path (if dropped by normalizer) |
|---|---|---|
| `date_of_birth` | `hit` | — |
| `document_number` | `hit` | — |
| `expiry_date` | `hit` | — |
| `first_name` | `miss` | — |
| `last_name` | `hit` | — |
| `personal_id` | `miss` | — |

