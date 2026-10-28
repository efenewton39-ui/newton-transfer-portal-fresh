# Newton Transfer Portal — Fresh setup

A mobile-friendly admin portal for creating, editing, searching, and tracking transfer **records**. It supports MXN (Mexican peso) and a destination details field for Mexican banks/accounts. It does not send money, connect to banks, validate CLABE/account ownership, or independently verify payments. Never mark a record Completed unless you have separately confirmed the transaction.

## Files and structure

- `app.py` — Flask application
- `requirements.txt` — Python dependencies
- `render.yaml` — Render deployment defaults
- `templates/` — all eight HTML templates (keep this folder and its files together)

## Deploy on Render

1. Create a **new, clean GitHub repository** for this project. Extract the ZIP and upload the contents of the `newton-transfer-portal-fresh` folder, including the complete `templates/` folder. Do not upload only the ZIP file.
2. In Render, create a Web Service from that repository and select branch `main`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variables: `APP_SECRET` (long random secret) and `ADMIN_PASSWORD` (a strong password you choose and keep private). `render.yaml` sets a temporary test database path.
6. Deploy and test the home page, admin login, create/edit, tracking, and print-to-PDF on the record detail page.

## Data persistence (important)

The default `/tmp/newton-transfer-portal/transfers.db` is for a quick test only. Data may disappear after restart/redeploy. Before storing real operational records, attach a persistent disk mounted at `/var/data` on an eligible Render plan and set `DATABASE_PATH=/var/data/transfers.db`, or configure a managed database. Check current pricing in Render before upgrading.

## Admin password

The app reads `ADMIN_PASSWORD` from Render environment settings. I cannot secretly know, hold, or recover your password; you control it. Set a strong unique value privately, and change it later in Render when you wish. Never send the password in chat.

## PDF

Open a record detail page and tap **Save / Print PDF**. In the phone/browser print dialog, choose **Save as PDF** if available. This is a printable record, not a bank-issued receipt or proof of payment.

## Before production

This package has had Python syntax and project-structure checks. A successful deployment/live test is still required; no one can honestly guarantee zero runtime errors without testing in the target Render environment.
