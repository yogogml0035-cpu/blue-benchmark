# M0 Scene Workspace Preview Review

Date: 2026-08-30

## Scope

Planning-only static HTML Preview. It does not claim current product runtime or
API implementation. It validates the proposed M0 information architecture,
visual hierarchy, responsive disclosure, and interaction shape before product
source changes.

## Direction

- Human: an internal business teacher turning recent delivery evidence into a
  reusable evaluation question.
- Focal action: answer or review the one current business question.
- Signature: `question -> answer -> latest changes -> one next action` remains a
  single vertical formation chain.
- Visual world: paper white, graphite, hairline gray, restrained ink blue,
  semantic amber. The primary command is neutral dark, not saturated blue.
- Rejected defaults: dashboard card wall, chat bubbles, permanent three-column
  workspace, AI ornaments, technical checkpoint console.

## Verified states

| View/state | Desktop | 390 x 844 | Result |
|---|---|---|---|
| Current question | `desktop-current.png` | `mobile-current.png` | PASS |
| Standards and evidence sheet | `desktop-sheet.png` | `mobile-sheet.png` | PASS |
| Next version / freeze risk | inspected | `mobile-versions.png` | PASS |

The Preview contains exactly three stable navigation labels: Current, Question,
Version. The current and version surfaces each expose one primary button. The
supporting evidence is closed by default, opens as a right sheet on desktop,
and occupies the full viewport on narrow screens.

## Mechanical browser checks

- Page title and semantic tablist present.
- No console errors after adding an inline favicon.
- Narrow viewport body `scrollWidth` equals viewport width: 390px.
- The narrow version view exposes buttons `查看入选题` and `检查并冻结`, with
  only the latter styled as primary.
- Escape closes the native dialog.
- Focus returns to `查看标准与依据` after dialog close.
- Current, Question, Version remain the only tabs at desktop and narrow widths.
- Motion uses transform/opacity and honors `prefers-reduced-motion`.

## Review conclusion

The direction passes the planning gate. It preserves the existing one-section
reading strength while replacing the obsolete route/card model with one scene
workspace. Production implementation must still cover the full Preview state
matrix and perform browser acceptance against real APIs; these screenshots are
visual evidence only.
