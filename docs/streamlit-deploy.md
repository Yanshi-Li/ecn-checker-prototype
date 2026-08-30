# Deploy the Streamlit app

1. Push this repository to GitHub.
2. Go to [Streamlit Community Cloud](https://share.streamlit.io/) and create a new app.
3. Select the GitHub repository and branch, then set the main file path to `streamlit_app.py`.
4. In the app dashboard, open **Settings → Secrets** and paste the real provider credentials using the keys shown in [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example). Do not put credentials in a committed file. `APP_PASSWORD` is required: it unlocks the Streamlit interface for a browser session.
5. Deploy the app. Community Cloud installs the dependencies listed in `requirements.txt` automatically.

The Streamlit interface displays only a password prompt until the user enters the configured `APP_PASSWORD`; successful authentication is retained for that browser session. For local testing, `APP_PASSWORD` can instead be supplied as an environment variable. After access is granted, the app runs intake, validation, advisory, context, and merge stages when **Run Checks** is selected. It does not send email on page load or when checks run. A user must separately enter the notification recipients and select **Send Notification Email**. Keep `DRY_RUN=true` in Streamlit secrets unless live SendGrid delivery has been explicitly approved.

## SendGrid sender verification

Before enabling real notification sends, verify the domain used by `EMAIL_FROM_ADDRESS` in the SendGrid dashboard. Use **Domain Authentication** (SPF/DKIM DNS records) for the long-term production setup, or **Single Sender Verification** for limited testing. SendGrid rejects mail from an unverified sender. This verification applies only to the sender address/domain; recipient domains, including `fisherpaykel.com`, require no SendGrid verification.

For local development, run:

```powershell
streamlit run streamlit_app.py
```

Use the files in `data/` as sample uploads, for example `data/ecn_intake.csv` and `data/bom.csv`.
