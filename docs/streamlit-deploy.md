# Deploy the Streamlit app

1. Push this repository to GitHub.
2. Go to [Streamlit Community Cloud](https://share.streamlit.io/) and create a new app.
3. Select the GitHub repository and branch, then set the main file path to `streamlit_app.py`.
4. In the app dashboard, open **Settings → Secrets** and paste the real provider credentials using the keys shown in [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example). Do not put credentials in a committed file.
5. Deploy the app. Community Cloud installs the dependencies listed in `requirements.txt` automatically.

The public Streamlit interface executes the intake, validation, advisory, context, and merge stages. It supports uploaded files and manual intake using the canonical staged intake glossary:

- `change_notice_number`
- `name_of_change`
- `reason_for_change`
- `description_of_change`
- `products_affected`
- `change_actions`
- `date`

Manual BOM rows use `line_number`, `part_number`, `description`, `quantity`,
`unit`, `action`, and `parent_part_no`. They are serialized and passed through
the same CSV-driven pipeline as uploaded files.

After checks complete, the user may explicitly click **Send Validation Email**.
The report is sent to `yanshili645@gmail.com`; it is not an approval or
rejection action and does not invoke the approval workflow. The button reports
whether SMTP is unavailable or the send failed.

For local development, configure these environment variables:

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=sender@example.com
SMTP_PASS=<secret>
```

For Streamlit Community Cloud, add the same keys under **Settings → Secrets**.
Secrets take precedence over environment variables. Never commit SMTP
credentials.

Password access control is temporarily disabled, so `APP_PASSWORD` is not required and the interface opens directly. Re-enable the `_require_access()` check in `streamlit_app.py` before deploying the app beyond this temporary testing period. The app runs intake, validation, advisory, context, and merge stages when **Run Checks** is selected. It does not send email on page load or when checks run. A user must separately enter the notification recipients and select **Send Notification Email**. Keep `DRY_RUN=true` in Streamlit secrets unless live SendGrid delivery has been explicitly approved.

## SendGrid sender verification

Before enabling real notification sends, verify the domain used by `EMAIL_FROM_ADDRESS` in the SendGrid dashboard. Use **Domain Authentication** (SPF/DKIM DNS records) for the long-term production setup, or **Single Sender Verification** for limited testing. SendGrid rejects mail from an unverified sender. This verification applies only to the sender address/domain; recipient domains, including `fisherpaykel.com`, require no SendGrid verification.

For local development, run:

```powershell
streamlit run streamlit_app.py
```

Use the files in `data/` as sample uploads, for example `data/ecn_intake.csv` and `data/bom.csv`.
