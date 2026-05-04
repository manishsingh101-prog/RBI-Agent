# RBI Circular Daily Email Agent — Setup Guide

This is a Python script that scrapes the RBI Notifications page once a day,
filters for circulars published today (or within the last N days), and emails
a clean digest to **manishsingh101@gmail.com**.

It is **not a hosted service** — you need to run it on something that's online
once a day. Three easy options below.

---

## 1. One-time setup

### a. Install Python 3.9+ and the dependencies

```bash
pip install requests beautifulsoup4 lxml
```

### b. Create a Gmail App Password (sender account)

The script sends mail via SMTP using a Gmail account *you* own — that
account is the **sender**, the recipient stays manishsingh101@gmail.com.

1. The sender Gmail account must have 2-Step Verification ON.
2. Go to <https://myaccount.google.com/apppasswords>
3. Create a new app password (name it "RBI Agent"). You'll get a 16-character code.
4. Save it — you'll use it as `SENDER_APP_PASSWORD` below.

You can use any SMTP provider (Outlook, Zoho, SES, SendGrid…) — just change
`SMTP_SERVER` and `SMTP_PORT` accordingly.

### c. Set environment variables

```bash
export SENDER_EMAIL="your_sender_account@gmail.com"
export SENDER_APP_PASSWORD="abcd efgh ijkl mnop"   # 16-char Gmail app password
# Optional:
export LOOKBACK_DAYS=1     # 1 = only today's circulars; 3 = covers Mon after weekend
export SMTP_SERVER="smtp.gmail.com"
export SMTP_PORT=465
```

### d. Test it once

```bash
python rbi_circular_agent.py
```

You should see a success message and an email in your inbox.

---

## 2. Schedule it to run daily

Pick **one** of these:

### Option A — Linux / macOS cron (easiest if you have a server or always-on Mac)

```bash
crontab -e
```

Add this line (runs every day at 9:00 AM IST, adjust path & timezone):

```
0 9 * * *  SENDER_EMAIL="..." SENDER_APP_PASSWORD="..." /usr/bin/python3 /full/path/to/rbi_circular_agent.py >> /var/log/rbi_agent.log 2>&1
```

### Option B — Windows Task Scheduler

1. Open Task Scheduler → **Create Basic Task**
2. Trigger: Daily at 9:00 AM
3. Action: Start a program
   - Program: `python.exe`
   - Arguments: `C:\path\to\rbi_circular_agent.py`
4. Set the env vars under the task's **Properties → Settings**, or use a `.bat`
   wrapper that exports them first.

### Option C — GitHub Actions (free, no server needed) ⭐ recommended

Create `.github/workflows/rbi.yml` in a private repo:

```yaml
name: RBI Daily Digest
on:
  schedule:
    - cron: "30 3 * * *"   # 09:00 IST = 03:30 UTC
  workflow_dispatch:        # lets you run it manually too

jobs:
  send:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install requests beautifulsoup4 lxml
      - run: python rbi_circular_agent.py
        env:
          SENDER_EMAIL:        ${{ secrets.SENDER_EMAIL }}
          SENDER_APP_PASSWORD: ${{ secrets.SENDER_APP_PASSWORD }}
          LOOKBACK_DAYS:       "1"
```

Then in your repo: **Settings → Secrets → Actions** → add `SENDER_EMAIL`
and `SENDER_APP_PASSWORD`. Done — fully free, runs forever.

---

## 3. Knobs you can tweak

| Variable / setting    | Default            | What it does                                  |
|-----------------------|--------------------|-----------------------------------------------|
| `RECIPIENT_EMAIL`     | manishsingh101@…   | Edit at top of script to change recipient     |
| `LOOKBACK_DAYS`       | 1                  | Window of days to include                     |
| `SEND_EMPTY_DIGEST`   | True               | If False, skips email when no circulars found |
| `SMTP_SERVER` / `PORT`| smtp.gmail.com:465 | Use any SMTP relay you prefer                 |

---

## 4. Notes & limits

- **Scraping breakage:** RBI's page is plain HTML and stable, but if they ever
  change the layout the date-extraction may need a tweak. The script is built
  to fail loudly (non-zero exit code) so cron/Actions will surface errors.
- **Be polite:** the script makes one HTTP request per run. Don't crank the
  schedule to once a minute — daily is plenty.
- **Holidays:** RBI doesn't publish on Sundays/holidays. With `LOOKBACK_DAYS=1`
  you'll get an "(no new circulars)" email on those days. Set it to `3` if
  you'd rather the Monday email pick up anything from the weekend.
