# ECN Checker Tester Guide

## 1. Purpose

ECN Checker helps users review an Engineering Change Notice (ECN) and its Bill of Materials (BOM) before the change is sent to the next reviewer.

The system:

1. accepts an ECN file and an optional BOM file;
2. extracts and normalizes the submitted information;
3. checks the submission against configured validation rules and reference data;
4. shows the result of each rule, including the reason and evidence where available;
5. produces an overall `PASS` or `FAIL` decision;
6. saves the evaluation so it can be reviewed later; and
7. supports an auditable email report workflow.

This is an evaluation prototype. A `PASS` or `FAIL` result is a system decision, not an engineering approval or rejection.

For technical details, see [Architecture](architecture.md), [Rule Schema](rules_schema.md), and [Evaluation Review Specification](evaluation-review-spec.md).

## 2. What testers are evaluating

The main evaluation task is:

> Upload an ECN and BOM, run a pre-check, understand which rules were checked and why each rule passed or failed, then judge whether the system result is correct and understandable.

Please evaluate both the **result** and the **experience**.

### Evaluate the result

- Did the system identify the relevant issues?
- Did it miss an issue that should have been reported?
- Did it report an issue that is not actually a problem?
- Is the overall `PASS` or `FAIL` decision reasonable?
- Are the rule explanations and evidence understandable?
- Does the result agree with your engineering judgement?

### Evaluate the experience

- Was it clear what file to upload?
- Was it clear when the check started and finished?
- Was the result easy to find?
- Could you understand what to fix after a `FAIL`?
- Were warnings clearly distinguished from blocking errors?
- Was the email action clear and appropriate?

## 3. Tester roles and terminology

### Tester

The person who uploads the ECN and BOM and runs the pre-check. Testers use an identified account so results can be connected to the person and evaluation session.

### Evaluation session

One tester's attempt to complete the evaluation task. A session may contain several events, such as uploading files, running a pre-check, submitting a judgement, and sending a notification.

### Pre-check attempt

One completed ECN/BOM check inside an evaluation session. Each attempt has its own result, timing, findings, and files.

### System decision

The result produced by ECN Checker: `PASS` or `FAIL`.

### Tester judgement

Your independent assessment of whether the system decision is correct. Record it separately from the system decision. For example:

| System decision | Tester judgement | Agreement |
|---|---|---|
| `FAIL` | `PASS` | No |

A disagreement is useful evidence. It may indicate a rule problem, unclear evidence, an unclear explanation, or a misunderstanding of the requirement.

### Checking duration

The elapsed time from selecting **Pre-check** until the result is available. Do not use the total time spent on the page as the checking duration.

## 4. Before you start

You need:

- an assigned tester account;
- the application URL, or the local application running on your machine;
- one ECN file;
- an optional BOM file for the test case;
- an email address for notification testing, if that scenario includes email; and
- enough time to record what you observed.

Use only approved test data. Do not upload confidential production documents unless the test owner has explicitly approved them.

Supported ECN formats include `.csv`, `.xlsx`, `.xls`, `.xlsm`, `.pdf`, `.html`, `.htm`, `.eml`, and `.txt` depending on the configured intake path. Supported BOM formats include `.csv`, `.xlsx`, `.xls`, `.xlsm`, and `.pdf`.

If you are testing locally, the application owner should provide the startup command and test account. The standard local web application command is:

```powershell
py scripts/app.py
```

Then open the local application URL supplied by the application owner, normally `http://localhost:5000`.

Do not place database passwords, SMTP passwords, or other credentials in this document or in a test result.

## 5. Standard tester procedure

### Step 1: Sign in

1. Open the application.
2. Sign in with your assigned tester email and password.
3. Confirm that the application identifies you as a tester.
4. If sign-in fails, record the error and stop the scenario. Do not repeatedly guess passwords.

### Step 2: Prepare the test case

Before uploading, record:

- test case name or identifier;
- ECN file name;
- BOM file name, if used;
- what you expect the correct result to be;
- which rules or data conditions the test is intended to exercise; and
- your expected email recipient, if applicable.

Do not change the files during the test unless the scenario explicitly asks you to correct and resubmit them.

### Step 3: Upload the ECN and BOM

1. Select the ECN file in the ECN upload field.
2. Select the BOM file in the BOM upload field, if the test case uses one.
3. Check that the displayed file names are correct.
4. Note any file-type or upload validation message.
5. Continue only when the correct files are selected.

The ECN is required. The BOM is optional for scenarios that test ECN-only validation, but the standard evaluation task uses both files.

### Step 4: Run the pre-check

1. Start a timer immediately before selecting **Pre-check**.
2. Select **Pre-check** once.
3. Stop the timer as soon as the result and findings are displayed.
4. Record the elapsed checking duration.
5. Do not refresh the page while the check is running unless the test scenario specifically asks you to test refresh or recovery behavior.

If the application reports that the check could not be completed, record the exact message, the files used, and whether the result was saved.

### Step 5: Review the result

Record the following information from the result screen:

- overall system decision: `PASS` or `FAIL`;
- number of errors or blockers;
- number of warnings;
- every rule ID shown;
- each rule's result or severity;
- the explanation for each finding;
- the location or field identified by the system;
- the evidence shown by the system;
- affected part numbers or BOM lines, where shown; and
- any AI advisory notes or unavailable/not-evaluated status.

Review blockers first, then warnings and advisory information. A warning does not necessarily close the gate. The system's gate behavior is described in [Architecture](architecture.md).

### Step 6: Give your tester judgement

After reading the complete result, decide independently whether the system's overall result is appropriate.

Submit:

- your overall judgement: `PASS` or `FAIL`;
- a short explanation of why you agree or disagree; and
- per-rule judgements where requested.

For each rule, use the available judgement value that best describes your assessment:

- `CORRECT` — the rule result is appropriate;
- `INCORRECT` — the rule result is wrong;
- `UNCLEAR` — there is not enough information to decide;
- `NOT_APPLICABLE` — the rule does not apply to this test case.

Do not change the system decision to make it match your judgement. The purpose of this test is to measure agreement and disagreement.

### Step 7: Test email behavior when required

Email testing must be performed only when the test scenario requests it and the application owner has enabled a safe test mail configuration.

#### Failed result

For a `FAIL` result:

1. Confirm that the result is shown as `FAIL`.
2. Enter the identified tester's email address as the recipient.
3. Send the validation report if the button is available.
4. Record whether the application reports `sent`, unavailable, or failed.
5. Confirm that the email contains the decision, blockers, and relevant findings.

A failed result is restricted to the tester's email address in the current workflow.

#### Passed result

For a `PASS` result:

1. Confirm that the result is shown as `PASS`.
2. Enter the approved next-checker email address.
3. Send the validation report if the scenario requires it.
4. Record whether the application reports `sent`, unavailable, or failed.
5. Confirm that the email identifies the result as a report and does not claim to be an approval.

Never use a real customer's or external person's email address for a test unless the test owner has approved it.

### Step 8: Record completion

Record:

- whether the evaluation was completed;
- the system decision;
- your judgement;
- whether you agreed with the system;
- checking duration;
- whether an email was requested;
- whether the email was sent successfully; and
- any usability issue, confusing wording, missing evidence, or unexpected behavior.

If you abandon the task, record the last successful step and the reason you stopped.

## 6. Suggested test cases

Use a mixture of passing, failing, and ambiguous cases. The exact expected result should be agreed with the test owner before execution.

| Test case | Purpose | Example expectation |
|---|---|---|
| Valid ECN and valid BOM | Confirm the normal successful path | The system returns `PASS` or explains any unexpected blocker |
| Missing required ECN field | Check required-field validation | The system identifies the missing field and explains how to correct it |
| Invalid or missing BOM part | Check part and context validation | The system identifies the affected part or context issue |
| Duplicate BOM line | Check structural BOM validation | The duplicate is identified with useful evidence |
| Zero or invalid quantity | Check quantity validation | The invalid quantity is identified and does not silently pass |
| Description/action mismatch | Check semantic advisory behavior | The system explains the mismatch and labels advisory status correctly |
| Unsupported file type | Check intake guidance | The upload is rejected with a clear supported-format message |
| Intentionally ambiguous case | Check human interpretation | The tester can mark the result `UNCLEAR` and explain why |
| Failed-result email | Check restricted notification path | The tester receives a report containing the failed findings |
| Passed-result email | Check next-checker notification path | The next checker receives a report without an approval claim |

Existing sample inputs and regression scenarios are documented in [Test Scenarios](test-scenarios.md).

## 7. What to report as a defect

Report a defect when the observed behavior differs from the expected behavior, especially when:

- the application accepts a file it should reject;
- the application rejects a valid file without explaining why;
- a rule is missing from the displayed result;
- a rule result or severity is incorrect;
- the explanation does not support the result;
- the overall decision contradicts the displayed blockers;
- the result shown to the tester is not saved;
- the checking duration is missing or clearly incorrect;
- a tester can access another tester's evaluation;
- an email is sent to an unauthorized recipient;
- an email claims approval when it is only a report; or
- a database or notification failure hides the validation result.

Include the following in a defect report:

- test case identifier;
- date and approximate time;
- tester account identifier, if permitted by the test owner;
- input file names, not confidential file contents;
- steps to reproduce;
- expected behavior;
- actual behavior;
- screenshot or redacted error message; and
- whether the evaluation was saved.

Never include passwords, API keys, SMTP credentials, database connection strings containing passwords, or confidential ECN/BOM contents in a defect report.

## 8. How evaluation results are used

The evaluation data supports three primary measurements:

### Checking duration

Measured from **Pre-check** start to result display. Compare durations across test cases and identify unusually slow checks.

### Pass/fail distribution

Calculate the percentage of completed evaluations whose system decision is `PASS` or `FAIL`.

### Agreement rate

Calculate agreement only for evaluations where a tester judgement exists:

> agreement rate = evaluations where tester judgement matches system decision ÷ evaluations with a tester judgement

Do not count missing judgements as disagreements.

Also review rule-level disagreements. A rule with frequent `INCORRECT` or `UNCLEAR` judgements may need clearer evidence, different logic, or additional domain review.

## 9. Important limitations

- The system is a prototype and is not a replacement for formal engineering approval.
- AI advisory output is advisory and may be unavailable or marked not evaluated.
- File parsing depends on recognizable templates and labels.
- Scanned or unusually formatted PDFs may not extract correctly.
- A failed persistence operation should not change the validation result; report any unsaved-evaluation warning.
- Test data should be controlled and approved because uploaded files may be retained for evaluation review.

## 10. Quick checklist

- [ ] I signed in with my assigned tester account.
- [ ] I recorded the test case and input file names.
- [ ] I uploaded the intended ECN and BOM.
- [ ] I timed the check from **Pre-check** to displayed result.
- [ ] I recorded the overall system decision.
- [ ] I reviewed every rule, explanation, and evidence item.
- [ ] I recorded my independent tester judgement.
- [ ] I recorded whether I agreed with the system.
- [ ] I tested email only when requested and used an approved test recipient.
- [ ] I reported confusing, missing, incorrect, or unsafe behavior.
- [ ] I did not include credentials or confidential data in my notes.
