# ECN Checker React frontend

This Vite + React + TypeScript application is the tester-facing pre-check interface. It calls Flask's staged pre-check endpoint, so Python remains responsible for intake, validation, PostgreSQL evaluation persistence, and audited email reports.

## Run locally

From the repository root, start the Flask validation backend. Set the database password and a long, private Flask session-secret value only in the terminal session:

```powershell flask-server.ps1
$env:ECN_DB_PASSWORD = Read-Host "Enter ecn_app database password"
$env:FLASK_SECRET_KEY = Read-Host "Enter a long random Flask session secret"
py scripts/app.py
```

In a second PowerShell window, install the frontend dependencies once and start Vite:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173`. Vite proxies `/api` and `/upload` requests to Flask at `http://127.0.0.1:5000`.

## Checks

```powershell
cd frontend
npm run typecheck
npm run build
```

## Login and accounts

The React UI starts at a login page. It uses the existing PostgreSQL `app_users` records, storing the authenticated user in Flask's signed session cookie. The pre-check page therefore gets the tester's email and display name from the signed-in account rather than asking for them in the upload form.

Create accounts from the repository root. The script prompts for passwords, so no password is placed in command history or source control:

```powershell create-tester.ps1
py scripts/create_evaluation_user.py --email tester@example.com --name "Test User" --role TESTER
```

Create reviewer and administrator accounts by substituting `REVIEWER` or `ADMINISTRATOR` for `TESTER`. A tester account can run pre-checks and send reports. Reviewer and administrator accounts are reserved for the protected review workflow.

When `ECN_DB_PASSWORD` and the related `ECN_DB_*` settings are configured, Flask stores the complete packet and original uploaded files in PostgreSQL.

The email path follows the gate decision:

- For a `FAIL`, the creator can email the validation report only to their own identified email address, so they can correct and resubmit it.
- For a `PASS`, the creator enters the next checker's email address and explicitly sends the validation report to that person.

Flask records the delivery outcome for either path. Reviewer authentication and review queues remain in Streamlit.
