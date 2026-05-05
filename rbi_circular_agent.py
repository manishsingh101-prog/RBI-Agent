#!/usr/bin/env python3
"""
RBI Circular Daily Email Agent
==============================
Fetches RBI circulars/notifications published on (or near) today's date from
https://www.rbi.org.in and emails a formatted digest to the recipient.

Run it daily via cron / Task Scheduler / GitHub Actions.

Usage:
    export SENDER_EMAIL="you@gmail.com"
    export SENDER_APP_PASSWORD="your_16_char_gmail_app_password"
    python rbi_circular_agent.py

Required Python packages:
    pip install requests beautifulsoup4 lxml
"""

import os
import re
import smtplib
import ssl
import sys
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURATION
# ============================================================
RBI_NOTIFICATIONS_URL = "https://www.rbi.org.in/Scripts/NotificationUser.aspx"

RECIPIENT_EMAIL = "manishsingh101@gmail.com"

# Sender credentials are read from environment variables (safer than hardcoding).
# For Gmail you must use an "App Password", not your normal password.
# Generate one here: https://myaccount.google.com/apppasswords
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_APP_PASSWORD")
SMTP_SERVER     = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT       = int(os.environ.get("SMTP_PORT", "465"))

# Look back this many days. Set to 1 to email only circulars dated today.
# Set to 3 to cover weekends/holidays when no circulars are published.
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "1"))

# Always send an email even when there are no new circulars
SEND_EMPTY_DIGEST = True

# Network
HTTP_TIMEOUT = 30
USER_AGENT   = "Mozilla/5.0 (compatible; RBICircularDigestBot/1.0)"

# ============================================================
# SCRAPING
# ============================================================
DATE_PATTERNS = [
    "%b %d, %Y",   # Oct 03, 2025
    "%B %d, %Y",   # October 03, 2025
    "%d %b %Y",    # 03 Oct 2025
    "%d %B %Y",    # 03 October 2025
    "%d-%m-%Y",    # 03-10-2025
    "%d/%m/%Y",    # 03/10/2025
]

DATE_REGEX = re.compile(
    r"(?:[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"            # Oct 03, 2025
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"               # 03 Oct 2025
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{4})"                  # 03/10/2025
)


def parse_date(text: str):
    """Find the first date in `text` and return a `date` object, else None."""
    if not text:
        return None
    m = DATE_REGEX.search(text)
    if not m:
        return None
    raw = m.group(0)
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def fetch_circulars():
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(RBI_NOTIFICATIONS_URL, headers=headers, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    circulars = []
    seen_urls = set()

    for link in soup.select("a[href*='NotificationUser.aspx?Id=']"):
        title = link.get_text(strip=True)
        href = link["href"]

        full_url = urljoin(RBI_NOTIFICATIONS_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        pub_date = None
        dept = ""

        # 🔍 Try multiple ways to extract date
        # Method 1: Parent row
        parent_row = link.find_parent("tr")
        if parent_row:
            text = parent_row.get_text(" ", strip=True)
            pub_date = parse_date(text)

        # Method 2: Previous/next sibling text
        if not pub_date:
            sibling_text = link.parent.get_text(" ", strip=True)
            pub_date = parse_date(sibling_text)

        # Method 3: Whole page fallback (rare)
        if not pub_date:
            surrounding = link.find_parent().get_text(" ", strip=True)
            pub_date = parse_date(surrounding)

        circulars.append({
            "title": title,
            "url": full_url,
            "date": pub_date,
            "dept": dept,
        })

    return circulars


def filter_recent(circulars, lookback_days):
    today = date.today()
    cutoff = today - timedelta(days=lookback_days - 1)

    result = []
    for c in circulars:
        if c["date"]:
            if cutoff <= c["date"] <= today:
                result.append(c)
        else:
            # include undated items (important fallback)
                       result.append(c)
    return result


# ============================================================
# EMAIL
# ============================================================
def build_html_email(circulars, lookback_days: int) -> str:
    today_str = date.today().strftime("%A, %d %B %Y")

    if not circulars:
        body = (
            f"<p>No new RBI circulars were found for the last "
            f"{lookback_days} day(s) as of {today_str}.</p>"
            f'<p>You can browse the full list here: '
            f'<a href="{RBI_NOTIFICATIONS_URL}">RBI Notifications</a></p>'
        )
    else:
        items = []
        # FIX: Handle None dates by sorting them to the end
        for c in sorted(circulars, key=lambda x: (x["date"] is None, x["date"]), reverse=True):
            d = c["date"].strftime("%d %b %Y") if c["date"] else "—"
            dept = f'<div style="color:#666;font-size:13px;">{c["dept"]}</div>' if c["dept"] else ""
            items.append(
                f'<li style="margin-bottom:14px;">'
                f'<div><strong>{d}</strong> &nbsp;'
                f'<a href="{c["url"]}" style="color:#0a58ca;text-decoration:none;">{c["title"]}</a></div>'
                f'{dept}'
                f'</li>'
            )
        body = (
            f"<p>Here are the RBI circulars from the last "
            f"{lookback_days} day(s) as of {today_str}:</p>"
            f'<ul style="padding-left:18px;">{"".join(items)}</ul>'
            f'<hr><p style="font-size:12px;color:#888;">'
            f'Source: <a href="{RBI_NOTIFICATIONS_URL}">rbi.org.in/Scripts/NotificationUser.aspx</a><br>'
            f'Sent automatically by your RBI Circular Agent.'
            f'</p>'
        )

    return f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
             color:#222;max-width:680px;margin:auto;padding:16px;">
  <h2 style="margin-bottom:6px;">RBI Circulars Digest</h2>
  <div style="color:#666;margin-bottom:18px;">{today_str}</div>
  {body}
</body></html>
"""


def send_email(html_body: str, subject: str):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise RuntimeError(
            "SENDER_EMAIL and SENDER_APP_PASSWORD environment variables must be set."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECIPIENT_EMAIL], msg.as_string())


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"[{datetime.now().isoformat()}] Fetching RBI circulars...")
    try:
        all_circulars = fetch_circulars()
    except Exception as e:
        print(f"ERROR fetching RBI page: {e}", file=sys.stderr)
        sys.exit(1)

    recent = filter_recent(all_circulars, LOOKBACK_DAYS)
    print(f"  Total found on page: {len(all_circulars)}")
    print(f"  Within last {LOOKBACK_DAYS} day(s): {len(recent)}")

    if not recent and not SEND_EMPTY_DIGEST:
        print("No new circulars; SEND_EMPTY_DIGEST=False, exiting.")
        return

    today_str = date.today().strftime("%d %b %Y")
    subject = (
        f"RBI Circulars — {today_str} ({len(recent)} new)"
        if recent else
        f"RBI Circulars — {today_str} (no new circulars)"
    )

    html = build_html_email(recent, LOOKBACK_DAYS)

    try:
        send_email(html, subject)
        print(f"  Email sent to {RECIPIENT_EMAIL}")
    except Exception as e:
        print(f"ERROR sending email: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
