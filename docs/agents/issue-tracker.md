# Issue Tracker

This repository uses GitHub Issues for work tracking. The repository is `Yanshi-Li/ecn-checker-prototype`; use the `gh` CLI from the repository root, which infers the repository from its Git remote.

## Conventions

- Create issues with `gh issue create --title "..." --body "..."`.
- Read issues with `gh issue view <number> --comments`.
- List issues with `gh issue list --state open` and appropriate label filters.
- Comment with `gh issue comment <number> --body "..."`.
- Apply or remove labels with `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close issues with `gh issue close <number> --comment "..."`.

## Specs

When an engineering skill says to publish a spec, create a GitHub issue. When it says to fetch a ticket, use `gh issue view <number> --comments`.

## Pull requests

Pull requests are not treated as a request surface for triage. Review pull requests explicitly with `gh pr` commands when needed.

## Wayfinding

Wayfinding maps use the `wayfinder:map` label. Decision tickets use one of `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`. Prefer GitHub sub-issues and native issue dependencies when supported; otherwise record parent and blocking relationships in issue bodies as described by the wayfinding skill.
