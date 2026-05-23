"""Latvian copy for wizard gating, consent gate, and auto-save indicator (P4 Slice C).

Centralising parent-facing strings here mirrors the pattern in
`apps.integrations.ocr_messages`: templates and JS reference these names so
no Latvian copy lives inline in markup, and no English fallback ever leaks
into the parent flow.
"""

from __future__ import annotations

# Inline error shown next to a required wizard field that blocks advancing.
STEP_FIELD_REQUIRED: str = "Šis lauks ir obligāts, lai turpinātu."

# Inline error shown when a field is filled but the format is invalid.
STEP_FIELD_FORMAT: str = "Lūdzu, pārbaudi ievadītā lauka formātu."

# Shown on step 1 when the personal-data-consent checkbox is unticked.
CONSENT_REQUIRED: str = "Lai turpinātu, ir jāpiekrīt personas datu apstrādei."

# Auto-save indicator labels — short by design (badge UI, max ~50 chars).
SAVE_INDICATOR_SAVING: str = "Saglabā…"
SAVE_INDICATOR_SAVED: str = "Saglabāts"
SAVE_INDICATOR_ERROR: str = "Nav saglabāts — pamēģini vēlreiz"
