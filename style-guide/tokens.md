# FK Cēsis Visual Tokens

**Status:** Canonical visual style source of truth for this repository.

## Source of truth

- `style-guide/FK Cesis.pdf`
- `style-guide/background-1.jpeg`
- this file
- `style-guide/tokens.css`

These files **supersede** exploratory values from `design-template.html` whenever there is a conflict.

## Fonts

- **Primary display / brand font:** `Anton`
- Fallback guidance for implementation planning: define safe fallbacks separately, but do not replace `Anton` as the intended brand font.

## Core colors

- **FK Cēsis blue:** `#0f0851`
- **FK Cēsis red:** `#ce1c20`

## Notes

- Treat the PDF and background image in this directory as authoritative visual reference materials.
- Any future design tokens added elsewhere in the repo must stay aligned with this file.
- If `design-template.html` differs from this directory, this directory wins.

## Component namespaces

Parent-UI partials use the `fk-*` BEM-style class prefix (matches existing `fk-alert`, `fk-section-card`, `fk-document-card`, `fk-hero-card`, etc.). The following namespaces are introduced by P4 Slice A foundations partials in `templates/parent_ui/includes/` and need styling in later P4 slices:

- `fk-spinner`, `fk-spinner__dot`, `fk-spinner__label` — calm async spinner (styling lands in P4 Slice B alongside the visibility-aware OCR polling).
- `fk-toast`, `fk-toast--success`, `fk-toast--warning`, `fk-toast--neutral`, `fk-toast__message` — auto-dismiss confirmation pill (styling + JS controller land in P4 Slice B).
- `fk-empty-state`, `fk-empty-state__title`, `fk-empty-state__body` — "no items yet" state (consumed by entry / portal / chooser polish in P4 Slice E).
- `fk-error-state`, `fk-error-state__title`, `fk-error-state__body` — page-level "something went wrong" state (consumed in P4 Slice E).

Each partial also exposes a stable `data-*` hook (`data-spinner`, `data-toast`, `data-toast-tone`, `data-empty-state`, `data-error-state`) for JS controllers to attach to.
