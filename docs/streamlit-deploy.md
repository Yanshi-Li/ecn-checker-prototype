# Deploy the Streamlit app

1. Push this repository to GitHub.
2. Go to [Streamlit Community Cloud](https://share.streamlit.io/) and create a new app.
3. Select the GitHub repository and branch, then set the main file path to `streamlit_app.py`.
4. In the app dashboard, open **Settings → Secrets** and paste the real provider credentials using the keys shown in [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example). Do not put credentials in a committed file.
5. Deploy the app. Community Cloud installs the dependencies listed in `requirements.txt` automatically.

The public Streamlit interface executes only the intake, validation, advisory, context, and merge stages. It does not invoke the approval workflow, so it does not send email when a visitor opens the app or runs checks.

For local development, run:

```powershell
streamlit run streamlit_app.py
```

Use the files in `data/` as sample uploads, for example `data/ecn_intake.csv` and `data/bom.csv`.
