# Operations runbook

How to run Tender Matcher for paying customers, and what to do when something goes wrong.
Customers rely on the daily digest to find work, so the two things that matter most are:
**the daily run happens every day**, and **no customer data is lost**.

## 1. Go live (one small server)

A 2 GB RAM Linux VM is enough for dozens of companies.

1. Install Docker, then copy the repository onto the server.
2. Create `.env` from `.env.example` and fill in at least:
   - `SAM_GOV_API_KEY`, `ANTHROPIC_API_KEY`
   - `DOMAIN` (e.g. `app.example.com`), with its DNS A record pointing at the server
   - `APP_BASE_URL=https://app.example.com`, `COOKIE_SECURE=true`
   - `POSTGRES_PASSWORD` (long and random)
   - `SMTP_*` and `SMTP_FROM` from a transactional email provider (Postmark, SES, Mailgun…)
   - `ADMIN_EMAIL`: who gets an email when a daily run has problems
3. Start everything: `docker compose --profile https up -d --build`
4. Check: `https://app.example.com` loads, `https://app.example.com/health/ready` answers.
   It says `degraded` until the first daily run finishes. The worker runs one immediately
   if none has run in the last 24 hours.
5. Create your own account first. To stop public sign-ups (invite-only), set
   `ALLOW_SIGNUP=false` and restart: `docker compose up -d`.

Only ports 80 and 443 should be open to the internet. The web container is bound to
`127.0.0.1:8000`, and Postgres is not published at all.

## 2. Every day, automatically

The `worker` service runs at `DAILY_RUN_HOUR_UTC` (default 11:00 UTC, early morning in the US):

1. Downloads the last three days of SAM.gov notices. Amended notices are judged again.
2. For every company with a saved profile: filter, rank, read the notice and attachments,
   judge, check every quote, score, and email the new strong/possible matches.
3. Records the run in `job_runs`, and emails `ADMIN_EMAIL` if anything failed.

If one company fails, the others still get their digest. If SAM.gov is down, notices
already downloaded are still judged and emailed. Each user's page shows when tenders were
last updated.

## 3. Monitoring

- Add `https://<domain>/health/ready` to an uptime monitor (UptimeRobot, Better Stack…),
  checked every 5 minutes, alerting on non-200. It returns 503 if the database is unreachable,
  if the last daily run had problems, or if no run finished in `STALE_AFTER_HOURS` (30 h).
- Logs: `docker compose logs -f worker` and `docker compose logs -f web`.
- Model spend: watch the Anthropic Console usage page. Each new notice judged costs one
  model call per company; already-judged notices are reused. `TOP_K` caps the calls per
  company per run, and `ATTACHMENT_CHAR_LIMIT` caps how much attachment text each call reads.

## 4. Backups (do this before the first customer)

The database holds every customer's profile, matches and feedback. Back it up daily and
keep copies **off the server**.

```bash
# /etc/cron.d/tender-matcher-backup: 03:30 every day, keep 30 days
30 3 * * * root cd /opt/tender-matcher && docker compose exec -T db pg_dump -U tender_matcher -Fc tender_matcher > /var/backups/tm-$(date +\%F).dump && find /var/backups -name 'tm-*.dump' -mtime +30 -delete
```

Then copy `/var/backups` to object storage (e.g. `rclone sync` to S3/B2) in the same cron.
**Test a restore once a month**; a backup you have never restored is not a backup:

```bash
docker compose exec -T db createdb -U tender_matcher restore_test
docker compose exec -T db pg_restore -U tender_matcher -d restore_test < /var/backups/tm-YYYY-MM-DD.dump
docker compose exec -T db psql -U tender_matcher -d restore_test -c "select count(*) from companies"
docker compose exec -T db dropdb -U tender_matcher restore_test
```

## 5. Common tasks

| Task | Command |
|---|---|
| Run the daily job now | `docker compose exec worker python -m app.jobs daily` |
| Set a user's password (no email set up, or they're locked out) | `docker compose exec worker python -m app.jobs set-password owner@example.com` |
| Deploy a new version | `git pull && docker compose --profile https up -d --build` (migrations run on start) |
| Roll back | check out the previous commit and run the same command. If that release added a migration, first `docker compose exec web alembic downgrade -1` |
| See recent runs | `docker compose exec db psql -U tender_matcher -c "select started_at, status, summary->'errors' from job_runs order by id desc limit 7"` |

## 6. When something goes wrong

| Symptom | Check |
|---|---|
| Admin alert "SAM.gov sync failed" | SAM.gov outage or an expired API key (SAM.gov keys expire every 90 days; renew at sam.gov → Account Details). Run the daily job again once fixed. |
| Many "The model call failed" skips | Anthropic status page, the API key, and the spend limits in the Console. |
| Many "quoted text that is not in the notice" skips | A model or prompt change; look at the worker logs for the failing notice IDs. Skipped notices are tried again on the next run. |
| Customers say emails don't arrive | SMTP credentials, and SPF/DKIM for `SMTP_FROM`'s domain with your email provider. |
| `/health/ready` is stale | `docker compose ps`: is `worker` running? `docker compose logs worker`. |

## 7. Known limits

- Sign-in throttling is kept in memory, so run **one** web process (the default). Move it
  to the database or Redis before scaling out.
- One user per company. A second person needs their own company account for now.
- Attachments: PDF (text-based, not scanned images), DOCX and plain text are read; other
  formats and image-only PDFs are skipped, so their requirements show as "unknown".
- Tenders closing within five days are filtered out as too late to bid.
- SAM.gov (US federal) only.
- The tool recommends and never bids. Every match must be checked against the official notice.
