# Triage3AM UI refresh v2 — restrained visual style

This version replaces the earlier neon gradients, glows, and constantly moving effects with a quieter charcoal interface, warm neutral accent color, flatter panels, more restrained typography, and a dotted wordmark that responds only when a pointer is near it.

## Files

Put both files in the repository's existing `static/` folder, replacing the older copies:

- `static/ui-refresh.css`
- `static/ui-refresh.js`

## Connect them (once)

In `static/index.html`, add this after the existing `style.css` link:

```html
<link rel="stylesheet" href="ui-refresh.css">
```

Add this after the existing `app.js` script tag near the bottom:

```html
<script src="ui-refresh.js"></script>
```

If you already added these two references in the previous step, do not add them again. Just replace the contents of the two existing files with this v2 version.

The script inserts the hero into `.main-container`, and keeps the existing analyzer logic/API unchanged.
