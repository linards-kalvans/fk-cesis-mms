# Favicon design

Date: 2026-06-29

## Problem

FK Cēsis MMS does not define a favicon. Browser tabs should use the same club icon as `www.fkcesis.lv`.

## Source asset

The current public site advertises this favicon in its `<head>`:

```html
<link rel="icon" type="image/png" href="//fkcesis.lv/cdn/shop/files/FK_Cesis_2.png?crop=center&height=32&v=1741252753&width=32">
```

The app will store a local copy instead of hotlinking the Shopify CDN asset.

## Scope

In scope:

- Add the current FK Cēsis favicon as a static PNG asset.
- Render it on parent/public pages.
- Render it on Django admin pages.

Out of scope:

- Logo redesign.
- PWA manifest.
- Apple touch icons.
- Any change to existing page styling or layout.

## Design

Use the smallest static-file path:

1. Store the fetched 32×32 PNG at `static/img/favicon.png`.
2. Add a favicon `<link rel="icon" type="image/png" ...>` to `templates/base.html` for parent/public pages.
3. Add the same favicon link to the Django admin base override so admin pages also show it.

## Acceptance criteria

- Parent/public rendered HTML includes `/static/img/favicon.png` as a PNG favicon.
- Django admin rendered HTML includes `/static/img/favicon.png` as a PNG favicon.
- The favicon file exists in repo static assets.
- No external favicon URL is used at runtime.
- Existing unrelated working-tree files are not modified.

## Test strategy

- Add minimal template/static assertions matching existing test style.
- Run full project gate:
  - `uv run pytest -q`
  - `uv run ruff check .`
  - `uv run mypy .`
