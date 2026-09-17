# Complete Evaluation Persistence and Reviewer Judgement

## Problem Statement

Single and batch ECN/BOM pre-checks currently persist only partial evaluation data. Reviewers cannot log in to inspect the complete result shown in Streamlit, download the original uploaded files, judge the overall PASS/FAIL decision and individual rules, or compare multiple reviewer judgements. This prevents measuring whether the system is usable and whether its decisions agree with human experts.

## Solution

Persist a complete, reviewable evaluation record for every single and batch pre-check. Store original files, extracted inputs, every displayed rule finding, gate decision, AI advisory, timings, and notification history. Add separate tester and reviewer roles with reviewer authentication, reviewer assignment, independent reviewer submissions, overall and per-rule judgements, comments, disagreement tracking, and reporting.

## User Stories

1. As an identified tester, I want every single pre-check saved so it can be reviewed later.
2. As an identified tester, I want every batch case saved separately so one case does not hide another case's outcome.
3. As a tester, I want the complete Streamlit result persisted so reviewers see the same evidence I saw.
4. As a tester, I want original ECN and BOM files retained so reviewers can inspect source documents.
5. As a reviewer, I want to download original uploaded files so I can validate the result against the source.
6. As a reviewer, I want extracted ECN and BOM data so I can inspect intake interpretation.
7. As a reviewer, I want every rule ID, severity, result, explanation, evidence, and location visible.
8. As a reviewer, I want the overall system PASS/FAIL decision visible.
9. As a reviewer, I want AI advisory notes and availability status visible.
10. As a reviewer, I want to judge the overall system result as PASS or FAIL.
11. As a reviewer, I want to judge each rule as CORRECT, INCORRECT, UNCLEAR, or NOT_APPLICABLE.
12. As a tester, I want to submit my own overall and per-rule judgements.
13. As a tester or reviewer, I want comments attached to overall and per-rule judgements.
14. As an administrator, I want to assign one or more reviewers to an evaluation.
15. As a reviewer, I want a separate authenticated reviewer area and an assigned-review queue.
16. As a reviewer, I want other reviewers' judgements hidden until I submit my own judgement.
17. As an administrator, I want each reviewer's submission stored independently.
18. As an administrator, I want conflicting reviewer decisions to mark an evaluation DISPUTED.
19. As an administrator, I want to resolve disputes while retaining the resolution history.
20. As a tester, I want completed reviewer results visible after review completion.
21. As a reviewer, I want evaluation status and assignment status visible.
22. As an analyst, I want PASS/FAIL percentages, checking durations, agreement rates, and rule-level disagreement reports.
23. As a tester, reviewer, or administrator, I want email requests, sends, and failures recorded in the same evaluation history.
24. As an administrator, I want incorrect rules flagged for review without automatically disabling them.
25. As a system operator, I want file names, MIME types, sizes, hashes, upload times, and evaluation relationships stored for traceability.
26. As a system operator, I want persistence failures shown clearly without hiding validation results.
27. As an administrator, I want engineering files and reviewer data protected by role and assignment checks.

## Implementation Decisions

- PostgreSQL remains the evaluation data store; the existing CSV-driven validation pipeline remains unchanged.
- A session represents an identified tester task. A pre-check attempt represents one single check or one independent batch case. A batch groups cases but does not replace them.
- Store a complete result snapshot containing gate decision, deterministic findings, context findings, AI advisory output, extracted intake data, summary counts, and all evidence displayed by Streamlit.
- Store original ECN/BOM bytes in PostgreSQL for the local prototype, plus filename, MIME type, size, SHA-256 hash, upload time, and evaluation relationship. Keep the storage interface replaceable by a later object-storage adapter.
- Keep system decisions, tester judgements, and reviewer judgements separate; none overwrites another.
- Overall judgements are PASS or FAIL. Per-rule judgements are CORRECT, INCORRECT, UNCLEAR, or NOT_APPLICABLE, each with an optional comment.
- Multiple reviewers are supported, and each submission is an independent record.
- Use Tester, Reviewer, and Administrator roles. Reviewers use a separate authenticated reviewer area. Administrators assign reviewers, manage accounts, resolve disputes, export data, and access all evaluations.
- Administrators assign reviewers. Reviewers cannot see other reviewers' unsubmitted judgements.
- Conflicting reviewer overall judgements produce DISPUTED status. A completed review without disagreement becomes REVIEWED. Administrator resolution is retained.
- Testers see reviewer judgements and comments only after review completion.
- Incorrect rules are flagged for administrator review and are not automatically disabled.
- Record notification requested, sent, and failed events with recipient, notification kind, timestamps, and safe error details; never store credentials.
- Use one evaluation persistence interface for Streamlit single-check and batch paths. PostgreSQL is the production adapter and an in-memory adapter is used by tests.
- Validation remains available if persistence is unavailable, with a clear unsaved-evaluation warning.
- Use evaluation statuses such as ACTIVE, READY_FOR_REVIEW, IN_REVIEW, REVIEWED, and DISPUTED, plus reviewer assignment statuses.
- Protect downloads and review records with role, ownership, and assignment checks; never expose raw files through unauthenticated URLs.
- Preserve audit history for reviewer and administrator actions.

## Testing Decisions

- Test at the highest application workflow seam available and assert persisted records and visible review behaviour, not private implementation details.
- Use an in-memory persistence adapter for deterministic fast tests and local PostgreSQL integration tests when explicitly configured.
- Cover complete single results, independent mixed-result batch cases, result snapshots, file bytes and metadata, timings, persistence failure warnings, tester/reviewer separation, multiple reviewers, hidden pre-submission judgements, DISPUTED status, completed-review visibility, per-rule metrics, and notification history.
- Follow existing evaluation-store, Streamlit, batch-orchestration, staged-pipeline, and notification regression-test patterns.

## Out of Scope

- Replacing validation rules or automatically disabling rules based on judgement.
- Direct Windchill, PLM, or ERP integration.
- Cloud storage or cloud PostgreSQL in the first local implementation.
- Anonymous sessions, public self-registration, corporate SSO, or automatic majority-vote rule changes.
- Destructive deletion of audit history.

## Further Notes

The local reviewer login must use secure password handling suitable for the prototype. The UI must make system decision, tester judgement, reviewer judgement, and agreement explicit. The data model must support duration, PASS/FAIL distribution, agreement, rule-level disagreement, and usability analysis.
