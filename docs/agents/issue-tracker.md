# Issue Tracker

This repository uses local Markdown files for work tracking. Keep issue records under `.scratch/<feature-slug>/`; `.scratch/` is ignored by Git so private planning notes are not committed or transferred when the repository is imported elsewhere.

## Conventions

- Create a feature directory under `.scratch/<feature-slug>/`.
- Store a feature spec at `.scratch/<feature-slug>/spec.md`.
- Store each ticket in its own file under `.scratch/<feature-slug>/issues/`, numbered from `01` (for example, `01-clarify-scope.md`).
- Record triage state with a `Status:` line near the top of each ticket. Use role names from `docs/agents/triage-labels.md` when applicable.
- Append discussion to the ticket under `## Comments`.
- Do not publish issue bodies, comments, or private planning links to GitHub Issues.

## Specs

When an engineering skill says to publish a spec, create or update `.scratch/<feature-slug>/spec.md`. When it says to fetch a ticket, read its local Markdown file.

## Wayfinding

Store each map at `.scratch/<effort>/map.md` and each decision ticket as a separate file under `.scratch/<effort>/issues/`. Use `Type:` for `research`, `prototype`, `grilling`, or `task`; use `Status:` for `claimed` or `resolved`; and use `Blocked by:` with ticket filenames or numbers for dependencies. The map is the index; ticket answers belong in their ticket files.

## Existing GitHub issues

Issues created before this tracker switch remain on GitHub and may still be public. Changing this configuration does not make existing issues private or delete them. Do not add new comments or issues to GitHub for this repository unless the user explicitly switches trackers again.

