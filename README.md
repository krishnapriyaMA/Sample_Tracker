# Sample Tracking System (web app)

FastAPI rebuild of the Golden / Shipment / Development Samples Power App, with real
auth, per-role page permissions, email notifications, and a dashboard. Defaults to
local SQLite so it runs immediately; point `DATABASE_URL` at Postgres and nothing
else changes.

## Run it locally

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # then edit .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 — the very first admin exists automatically
(`ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`, defaults to
`krishnapriya.m@jandjsourcing.com` / `ChangeMe123!`). Log in with that, then
change its password from the "Change password" link in the sidebar. Everyone
else creates their own account at `/register` with their Outlook email and
their own password — no one, including admins, ever needs to type in anyone
else's password.

## Connecting Postgres

Drop your connection string into `.env`:

```
DATABASE_URL=postgresql://user:password@host:port/dbname
```

Tables are created automatically on startup via `app/seed.py` (called from
`main.py`'s startup event) — no separate migration step needed for this first
version. If you outgrow that, add Alembic.

## What's implemented

- **Golden / Shipment / Development Samples**: list with search + filters, add/edit
  (modal forms), delete with confirm, image upload on Golden and Development records.
  Field sets match your live Power App screens exactly (Shipment Samples uses
  Buyer Ref / PO No / Vendor / Barcode / Rack no. / Description / Buyer / Date / Finish).
- **Scheduled notification jobs** (`app/scheduled_jobs.py`), all silently no-op
  without breaking anything if `SMTP_HOST` isn't set:
  - *Golden Samples*, monthly (1st, 8am): reports every `Active` item; anything
    2+ years past its **Start Date** is flagged `[RENEWAL DUE]` — nothing changes
    automatically, since items sometimes get renewed and the start date just
    needs a manual update. The UI shows the same flag with a "Renewal due" filter.
  - *Development Samples*, every 2 weeks: everything with status **"Pending Return"**,
    grouped by Client and routed to that client's team via the mapping you set
    in `/admin` (falls back to `SMTP_NOTIFY_DEFAULT` for any client without a mapping).
  - *Development Samples*, quarterly (Jan/Apr/Jul/Oct 1st): full report to the
    manager list you maintain in `/admin`.
  - *Shipment Samples*, monthly (1st, 8:30am): everything where **Date** is more
    than a year old and not yet marked disposed. The UI shows a matching
    "Disposal due" badge and filter, plus a "Mark disposed" action.
  - A daily 8am check for individually overdue Development Sample returns
    (separate from the biweekly digest — this one's the immediate reminder).
- **Access control**: two roles, `admin` and `user`. Admins get full access to
  everything automatically. New `user` accounts start with **zero page access**
  — an admin grants view/edit access **per person, per page** from `/admin`,
  matched to their email. This replaces the Power App's hardcoded
  `User().Email in [...]` check with something actually manageable.
- **Auth**: self-service registration at `/register` — people sign up with their
  Outlook email and set their own password (nobody else ever sees it). Optional
  `ALLOWED_EMAIL_DOMAIN` env var restricts sign-ups to your company domain.
- **Dashboard**: record counts, status breakdown charts (Chart.js), renewal-due
  and disposal-due counts, overdue development returns, recent activity feed.
- **Activity log**: every create/update/delete/status-change is recorded
  (`app/models.py: ActivityLog`) — feeds the dashboard and gives you an audit
  trail Power Apps never had.

## Data model source

Field names were pulled directly from the `.msapp` source (`golden_samples`,
`Shipment_Samples`, `development_samples` SharePoint lists) — see
`app/models.py` for the mapping.

## Migrating data from Power App CSV exports

`scripts/migrate_golden_samples.py` does a one-time import of a Golden Samples
SharePoint list export into the `golden_samples` table:

```bash
python -m scripts.migrate_golden_samples path\to\golden_samples.csv
```

It reads `DATABASE_URL` from `.env` the same way the app does, so make sure
that's pointed at the right database first. Duplicate SKU entries in the
export (the same item listed more than once) are automatically collapsed into
one record, keeping whichever copy has the most complete data. **Run it once**
— rows with a blank SKU have no way to be matched on a re-run, so running it
twice will duplicate those specific rows. The script prints a summary
including any Client values that don't match your Lowes/Topps/Wickes/Adeo/OBI
dropdown, so you can decide whether to expand that list or clean up the data.

## Suggested next steps

1. Swap the default `SECRET_KEY` and admin password before any real deployment.
2. Point `DATABASE_URL` at your Postgres instance and confirm the seed script
   creates tables cleanly there (SQLite and Postgres mostly agree on these
   simple types, but re-test after switching).
3. Fill in `SMTP_*` env vars to turn on real email notifications.
4. If you want image uploads to survive redeploys on Render, move
   `app/static/uploads` to S3 or another persistent store — local disk on
   Render's free tier doesn't persist across deploys.
5. If you'd rather people not manage a separate password at all, "Sign in with
   Microsoft" (Azure AD / Entra ID OAuth) is a natural next step — it needs an
   App Registration in your org's Microsoft 365 tenant admin center. Happy to
   wire that up whenever that access is available; it can sit alongside the
   current email/password login rather than replacing it.
