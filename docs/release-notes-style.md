# Release Notes Style Guide

GridFront Scout uses the same release-note habit as the platform app:
human-readable notes are written before release, then automation stamps the
version and date.

## Workflow

1. If a change affects what an operator, installer, or field tech will see,
   edit `release-notes.json`.
2. Replace the `pending` placeholder with one or more notes in plain English.
3. Do not guess the version number. `scripts/bump-version.js` stamps it when
   the release is cut.
4. Internal-only work can skip release notes when the commit or PR title uses
   an internal prefix such as `chore:`, `test:`, `refactor:`, `ci:`, `docs:`,
   `build:`, `perf:`, or `style:`.

## Audience

Write for people using or maintaining the tablet/OAK system in the field.
They care about what changed, whether setup is easier, whether alerts are more
reliable, and whether the live radar behaves differently.

## Tone

- Plain English, active voice, past tense.
- Explain the operator benefit before implementation details.
- Avoid commit prefixes, PR numbers, branch names, and internal shorthand.
- No hype. Specific beats dramatic.
- No emojis.

## Shape

Use this shape inside `release-notes.json`:

```json
{
  "title": "Short benefit-focused title",
  "kind": "patch",
  "description": "One or two sentences explaining what changed and why it matters.",
  "items": [
    "Optional bullet with a concrete detail.",
    "Another complete thought, ending with a period."
  ]
}
```

Use `patch` for fixes and small polish, `minor` for meaningful new capability,
and `major` only for a compatibility break or a product-level reset.

## Good Examples

- "The radar now clears stale detections as soon as the OAK link drops, so the
  screen does not freeze on the last person it saw."
- "Installers can now adjust camera position from the tablet and have the OAK
  pick up the new config without reflashing."
- "Behind-the-scenes reliability work for the tablet boot flow. No visible
  change, but startup failures are easier to diagnose."
