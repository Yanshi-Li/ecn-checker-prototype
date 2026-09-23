# ECN Checker React frontend

This Vite + React + TypeScript application is the tester-facing pre-check interface. It calls Flask's staged pre-check endpoint, so Python remains responsible for intake, validation, PostgreSQL evaluation persistence, and audited email reports.

## Run locally

From the repository root, start the Flask validation backend:

```powershell
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

The React UI requires the tester's email so each pre-check can be saved for review. When `ECN_DB_PASSWORD` and the related `ECN_DB_*` settings are configured, Flask stores the complete packet and original uploaded files in PostgreSQL.

The email path follows the gate decision:

- For a `FAIL`, the creator can email the validation report only to their own identified email address, so they can correct and resubmit it.
- For a `PASS`, the creator enters the next checker's email address and explicitly sends the validation report to that person.

Flask records the delivery outcome for either path. Reviewer authentication and review queues remain in Streamlit.
