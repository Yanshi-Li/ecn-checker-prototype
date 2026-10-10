# One-Hour Laptop Test Session Guide

This guide is for testing AI ECN Checker on a laptop that will be temporarily handed to a colleague. It is designed for a short, controlled session without exposing the application or PostgreSQL database to the internet.

The colleague uses the React frontend locally at `http://localhost:5173`. The React frontend calls the Flask backend at `http://127.0.0.1:5000`, and the backend connects to local PostgreSQL. The laptop owner prepares the application before the session and removes test credentials and data afterwards.

## Safety rules

- Do not expose PostgreSQL port `5432` to the internet.
- Do not commit `.env` or any password to Git.
- Use sample or approved anonymized ECN/BOM files only.
- Use a test email mailbox, not a real customer or production recipient.
- Keep real email delivery disabled unless the test coordinator explicitly enables it.
- Do not let the colleague use the PostgreSQL administrator account.
- Do not leave the laptop unlocked or unattended during the session.

## What this test can measure

This setup is suitable for testing:

- Upload and file-selection behavior
- ECN/BOM pre-check behavior
- Rule explanations and evidence
- System `PASS`/`FAIL` decisions
- Tester judgements and agreement with the system
- Approximate checking duration
- Local email dry-run or controlled email behavior
- Whether evaluation records are saved locally

It is not suitable for testing public deployment, multiple simultaneous users, internet availability, or production email reliability.

## 1. Laptop owner preparation

Complete these steps before handing over the laptop.

### 1.1 Confirm the project is available

Open PowerShell in the repository root and confirm that the project files are present:

```powershell
git status
```

Do not continue if the repository contains uncommitted secrets or private production files.

### 1.2 Create or activate the Python environment

If the project environment does not exist:

```powershell
py -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
py -m pip install -r requirements.txt
```

If PowerShell blocks activation, use the Python executable directly instead:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 1.3 Install and verify the React frontend

The tester-facing interface is the Vite + React application in `frontend/`. From the repository root, install its dependencies:

```powershell
cd frontend
npm install
npm run typecheck
npm run build
cd ..
```

The typecheck and build should complete successfully before the laptop is handed over. The colleague should test through the React interface, not through the legacy HTML upload page at port `5000`.

### 1.4 Confirm PostgreSQL is running

PostgreSQL must be running as a local Windows service. The evaluation database should be:

- Database: `ecn_prechecker_evaluation`
- Application user: `ecn_app`
- Host: `localhost`
- Port: `5432`

The application user must have its own password. Do not configure the application with the PostgreSQL administrator account.

### 1.5 Configure local settings

Create `.env` in the repository root if it does not exist. Use the approved local values supplied by the application owner.

At minimum, the evaluation store needs settings equivalent to:

```text
ECN_DB_HOST=localhost
ECN_DB_PORT=5432
ECN_DB_NAME=ecn_prechecker_evaluation
ECN_DB_USER=ecn_app
ECN_DB_PASSWORD=<local application password>
```

Keep the actual password private. Do not put it in this guide, a screenshot, or the test notes.

For a safe test session, keep email in dry-run mode unless controlled delivery is required:

```text
DRY_RUN=true
```

If the application requires administrator bootstrap settings, configure them before the session and create a separate tester account. Do not give the colleague the administrator credentials.

### 1.6 Initialize the evaluation database

Run the schema initialization command from the repository root:

```powershell
py scripts/initialise_evaluation_db.py
```

The command may ask for the database password. Enter it privately when prompted.

Confirm that initialization completes successfully. If it fails, fix the database setup before the test session; do not ask the colleague to troubleshoot PostgreSQL during the one-hour session.

### 1.7 Prepare test files

Create a clearly labelled test folder, for example:

```text
test-session-files/
├── 01-valid-ecn.csv
├── 01-valid-bom.csv
├── 02-missing-field-ecn.csv
├── 02-valid-bom.csv
├── 03-invalid-quantity-ecn.csv
└── 03-invalid-quantity-bom.csv
```

Use the minimum number of files needed for the planned scenarios. Confirm that the files contain no confidential production information.

### 1.8 Create the tester handout

Give the colleague:

- This guide, or the relevant testing sections
- [`docs/tester-guide.md`](tester-guide.md)
- The test files
- The tester email and password
- The test scenario list
- The test mailbox address, if email is being tested

Do not give the colleague:

- PostgreSQL credentials
- Administrator credentials
- SMTP credentials
- AI provider keys
- Access to the `.env` file

## 2. Start the React application

The React frontend requires two processes: the Flask backend and the Vite development server. Open two PowerShell windows.

### 2.1 Start the Flask backend

In the first PowerShell window, from the repository root, run:

```powershell
py scripts/app.py
```

Leave this window open during the test. The backend must remain running while the React frontend is being used.

### 2.2 Start the Vite frontend

In the second PowerShell window, from the repository root, run:

```powershell
cd frontend
npm run dev
```

Vite normally starts the React interface at:

```text
http://localhost:5173
```

Open that Vite URL in the browser. Do not ask the colleague to use the backend URL directly. Vite proxies `/api` requests to Flask at `http://127.0.0.1:5000`.

Confirm all of the following before starting the one-hour session:

- The React login page loads.
- The tester can sign in.
- The tester can see the pre-check screen.
- The backend PowerShell window shows no startup error.
- PostgreSQL is running.

If the application does not start, check both PowerShell windows. Do not expose either server through Windows firewall rules or router port forwarding for this test.

## 3. One-hour test plan

Use this schedule to keep the session focused.

| Time | Activity |
|---|---|
| 0–5 minutes | Explain the task and provide the tester account |
| 5–10 minutes | Tester signs in and confirms the upload screen |
| 10–25 minutes | Tester runs a valid ECN/BOM scenario |
| 25–40 minutes | Tester runs one or two failing scenarios |
| 40–50 minutes | Tester records judgements and tests email if enabled |
| 50–58 minutes | Tester completes usability feedback |
| 58–60 minutes | Tester signs out and returns the laptop |

Allow the colleague to attempt the workflow without coaching during the first run. Explain only what is necessary for them to begin. Their confusion is useful usability evidence.

## 4. Colleague test procedure

The colleague should follow these steps.

### 4.1 Sign in

1. Open `http://localhost:5173`.
2. Sign in using the assigned tester account.
3. Confirm that the account is identified as a tester.
4. Do not open database tools or configuration files.

### 4.2 Run the standard scenario

1. Select the ECN file.
2. Select the BOM file.
3. Note the time immediately before selecting **Pre-check**.
4. Select **Pre-check** once.
5. Note the time when the findings appear.
6. Record the checking duration.
7. Read every displayed rule, severity, explanation, and evidence item.
8. Record the system decision: `PASS` or `FAIL`.
9. Record an independent tester judgement.
10. Record whether the judgement agrees with the system.

The colleague should not be told the expected result until after recording their own judgement if the purpose is to measure independent interpretation.

### 4.3 Run a failing scenario

Use a controlled scenario such as a missing required field or invalid BOM quantity.

The colleague should check:

- Whether the correct rule is shown
- Whether the affected field or row is identified
- Whether the explanation describes the problem
- Whether the suggested correction is useful
- Whether the overall decision is consistent with the finding

### 4.4 Test notification behavior, if enabled

Use only the approved test mailbox.

For a `FAIL` result, send only to the submitting tester address unless the test plan explicitly tests recipient rejection.

For a `PASS` result, send to the approved next-checker test address.

Record whether the application reports:

- sent;
- unavailable;
- failed; or
- rejected.

The email is a validation report. It is not an approval or rejection decision.

## 5. Test notes to collect

Use a separate worksheet or text file. Do not write notes into `.env`.

For each attempt, record:

| Field | Value |
|---|---|
| Test case | |
| Tester | |
| ECN filename | |
| BOM filename | |
| Pre-check start time | |
| Result displayed time | |
| Checking duration | |
| System decision | `PASS` / `FAIL` |
| Tester judgement | `PASS` / `FAIL` |
| Agreement | Yes / No |
| Rule disagreement | |
| Email requested | Yes / No |
| Email result | |
| Usability comments | |

Ask the colleague:

1. What did you expect to happen?
2. What happened instead?
3. Was it clear which rule caused the result?
4. Was the explanation understandable?
5. What was the hardest step?
6. What should be improved first?

## 6. After the colleague finishes

### 6.1 Ask the colleague to sign out

The colleague should sign out of the application and close the browser.

### 6.2 Stop the application

Return to the PowerShell window running the app and use the application shutdown command appropriate to the current terminal. Do not leave the app running after the laptop is returned.

### 6.3 Remove temporary access

The laptop owner should:

- disable or delete the temporary tester account;
- remove test files from the laptop if they are no longer needed;
- remove temporary exported reports;
- clear the browser's saved passwords and downloads;
- rotate any temporary email credentials if they were used; and
- confirm that `.env` remains excluded from Git.

### 6.4 Review saved evaluations

From the administrator or database operator workflow, confirm that the test records contain:

- tester identity;
- uploaded file metadata;
- system decision;
- rule findings;
- checking timestamps;
- tester judgement;
- agreement; and
- notification history, if tested.

Do not edit the saved system decision to match the tester judgement. They must remain separate.

## 7. If something goes wrong

If the application fails during a test:

1. Record the exact visible message.
2. Record the last successful step.
3. Record the filenames used.
4. Record whether the result was saved.
5. Do not repeatedly submit the same file if it may create duplicate evaluations.
6. Tell the application owner before changing configuration.

Do not ask the colleague to repair PostgreSQL, edit `.env`, install unknown software, or change firewall settings during the session.

## 8. Success criteria

The one-hour test is successful when the colleague can:

- sign in without assistance;
- upload the assigned ECN and BOM;
- start a pre-check;
- understand the displayed rule findings;
- identify why the system returned `PASS` or `FAIL`;
- submit an independent judgement;
- complete at least one valid and one failing scenario; and
- provide concrete usability feedback.

A successful session does not require every system result to be correct. Disagreements and unclear explanations are valuable findings for improving AI ECN Checker.
