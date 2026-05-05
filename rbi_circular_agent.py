#!/usr/bin/env python3
"""
RBI Circular Daily Email Agent (Enhanced)
==========================================
Fetches RBI circulars with all details: Date, Department, Circular Number, 
Attachment links, and formats them as per RBI official format.

Usage:
    export SENDER_EMAIL="you@gmail.com"
    export SENDER_APP_PASSWORD="your_16_char_gmail_app_password"
    python rbi_circular_agent.py

Required packages:
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

SENDER_EMAIL    = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_APP_PASSWORD")
SMTP_SERVER     = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT       = int(os.environ.get("SMTP_PORT", "465"))

LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "1"))
SEND_EMPTY_DIGEST = True

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
    r"(?:[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{4})"
)

CIRCULAR_NUMBER_REGEX = re.compile(
    r"(?:RBI/\d{4}-\d{2}/\d+|CIR/\w+/\d+|[A-Z\.]+\s*Circular\s+No\.?\s*\d+)"
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


def extract_circular_number(text: str):
    """Extract circular/notification number from text."""
    if not text:
        return ""
    m = CIRCULAR_NUMBER_REGEX.search(text)
    return m.group(0) if m else ""


def extract_department(text: str):
    """Extract department name from circular text."""
    if not text:
        return ""
    
    departments = [
        "Monetary Policy",
        "Banking Regulation",
        "Foreign Exchange",
        "Reserve Bank",
        "Financial Services",
        "Debt Management",
        "Payment Systems",
        "Department of Banking Regulation",
        "Department of Corporate Services",
        "RBI",
    ]
    
    text_lower = text.lower()
    for dept in departments:
        if dept.lower() in text_lower:
            return dept
    return ""


def fetch_circulars():
    """Fetch all circulars from RBI page with complete details."""
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(RBI_NOTIFICATIONS_URL, headers=headers, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    circulars = []
    seen_urls = set()

    # Parse table rows containing circulars
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        # Extract data from cells
        link = row.find("a", href=re.compile(r"NotificationUser\.aspx\?Id="))
        if not link:
            continue

        title = link.get_text(strip=True)
        href = link.get("href", "")
        full_url = urljoin(RBI_NOTIFICATIONS_URL, href)

        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Extract publication date
        pub_date = parse_date(row.get_text(" ", strip=True))

        # Extract circular number
        circular_num = extract_circular_number(title) or extract_circular_number(row.get_text(" "))

        # Extract department
        dept = extract_department(row.get_text(" "))

        # Extract attachment/PDF link
        attachment_link = ""
        pdf_link = row.find("a", href=re.compile(r"\.pdf|download", re.I))
        if pdf_link:
            attachment_link = urljoin(RBI_NOTIFICATIONS_URL, pdf_link.get("href", ""))

        circulars.append({
            "title": title,
            "url": full_url,
            "date": pub_date,
            "dept": dept,
            "circular_num": circular_num,
            "attachment": attachment_link,
        })

    return circulars


def filter_recent(circulars, lookback_days):
    """Filter circulars from the last N days."""
    today = date.today()
    cutoff = today - timedelta(days=lookback_days - 1)

    result = []
    for c in circulars:
        if c["date"]:
            if cutoff <= c["date"] <= today:
                result.append(c)
        else:
            result.append(c)  # Include undated items as fallback
    return result


# ============================================================
# EMAIL
# ============================================================
def build_html_email(circulars, lookback_days: int) -> str:
    """Build formatted HTML email matching RBI official format."""
    today_str = date.today().strftime("%A, %d %B %Y")

    if not circulars:
        body = (
            f"<p>No new RBI circulars were found for the last "
            f"{lookback_days} day(s) as of {today_str}.</p>"
            f'<p>You can browse the full list here: '
            f'<a href="{RBI_NOTIFICATIONS_URL}">RBI Notifications</a></p>'
        )
    else:
        # Sort by date (handle None dates)
        sorted_circulars = sorted(
            circulars, 
            key=lambda x: (x["date"] is None, x["date"]), 
            reverse=True
        )

        table_rows = []
        for i, c in enumerate(sorted_circulars, 1):
            date_str = c["date"].strftime("%d-%m-%Y") if c["date"] else "—"
            dept = c["dept"] or "—"
            circ_num = c["circular_num"] or "—"
            
            # Build attachment link
            attach_html = ""
            if c["attachment"]:
                attach_html = f'<a href="{c["attachment"]}" style="color:#0a58ca;text-decoration:none;">📎 Download PDF</a>'
            else:
                attach_html = '<a href="' + c["url"] + '" style="color:#0a58ca;text-decoration:none;">📎 View</a>'

            table_rows.append(f"""
            <tr style="border-bottom:1px solid #ddd;">
                <td style="padding:10px;text-align:center;font-weight:bold;">{i}</td>
                <td style="padding:10px;">{date_str}</td>
                <td style="padding:10px;">{dept}</td>
                <td style="padding:10px;"><strong>{circ_num}</strong></td>
                <td style="padding:10px;">
                    <a href="{c['url']}" style="color:#0a58ca;text-decoration:none;">{c['title']}</a>
                </td>
                <td style="padding:10px;text-align:center;">
                    {attach_html}
                </td>
            </tr>
            """)

        body = f"""
        <p><strong>RBI Circulars from the last {lookback_days} day(s) as of {today_str}:</strong></p>
        <table style="width:100%;border-collapse:collapse;border:1px solid #ddd;">
            <thead>
                <tr style="background-color:#f5f5f5;font-weight:bold;">
                    <th style="padding:10px;border:1px solid #ddd;text-align:center;">Sr</th>
                    <th style="padding:10px;border:1px solid #ddd;">Date</th>
                    <th style="padding:10px;border:1px solid #ddd;">Department</th>
                    <th style="padding:10px;border:1px solid #ddd;">Circular No.</th>
                    <th style="padding:10px;border:1px solid #ddd;">Subject/Title</th>
                    <th style="padding:10px;border:1px solid #ddd;text-align:center;">Attachment</th>
                </tr>
            </thead>
            <tbody>
                {"".join(table_rows)}
            </tbody>
        </table>
        <p style="font-size:12px;color:#888;margin-top:20px;">
            <strong>Source:</strong> <a href="{RBI_NOTIFICATIONS_URL}">RBI Notifications Page</a><br>
            Sent automatically by RBI Circular Agent
        </p>
        """

    return f"""\
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; color: #222; max-width: 900px; margin: auto; padding: 16px; }}
        table {{ font-size: 14px; }}
        a {{ color: #0a58ca; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <h2 style="margin-bottom:6px;">RBI Circulars Digest</h2>
    <div style="color:#666;margin-bottom:18px;">{today_str}</div>
    {body}
</body>
</html>
"""


def send_email(html_body: str, subject: str):
    """Send formatted email via Gmail SMTP."""
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
