# ECN Checker React frontend

This Vite + React + TypeScript application is the new tester-facing pre-check interface. It calls the existing Flask upload endpoint, so Python remains responsible for file intake and validation decisions.

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

The React UI currently supports the tester's file-upload pre-check workflow and result review. Reviewer authentication, evaluation persistence, and email-sharing controls remain in the Streamlit application until their Flask API contracts are added.
