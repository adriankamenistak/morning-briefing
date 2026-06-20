"""
Morning Briefing Script
-----------------------
Fetches Gmail, Google Calendar, Google Keep, and Notion data,
asks Claude to summarize it, then sends it via ntfy.

Setup: see README.md
"""

import os
import json
import pickle
import requests
from datetime import datetime, timedelta, timezone

import anthropic
import gkeepapi
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── CONFIG ────────────────────────────────────────────────────────────────────
from config import (
    ANTHROPIC_API_KEY, NOTION_API_KEY, NOTION_EXTRA_PAGES,
    NOTION_TESTS_DB_ID, NTFY_TOPIC, GOOGLE_EMAIL, GOOGLE_APP_PASS
)

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")
TOKEN_FILE       = os.path.join(SCRIPT_DIR, "token.pickle")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
# ─────────────────────────────────────────────────────────────────────────────


def get_google_creds():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return creds


def get_emails(gmail):
    result = gmail.users().messages().list(
        userId="me",
        q="is:unread newer_than:1d -category:promotions -category:social -category:forums",
        maxResults=15,
    ).execute()
    messages = result.get("messages", [])
    summaries = []
    for msg in messages[:10]:
        detail = gmail.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        h = {x["name"]: x["value"] for x in detail["payload"]["headers"]}
        summaries.append({
            "from":    h.get("From", "?"),
            "subject": h.get("Subject", "(no subject)"),
            "date":    h.get("Date", ""),
        })
    return summaries


def get_calendar(cal):
    now = datetime.utcnow()
    day_start = datetime(now.year, now.month, now.day).isoformat() + "Z"
    day_end   = (datetime(now.year, now.month, now.day) + timedelta(days=2)).isoformat() + "Z"
    result = cal.events().list(
        calendarId="primary",
        timeMin=day_start,
        timeMax=day_end,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = []
    for e in result.get("items", []):
        events.append({
            "title":    e.get("summary", "Untitled"),
            "start":    e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
            "end":      e.get("end",   {}).get("dateTime", e.get("end",   {}).get("date", "")),
            "location": e.get("location", ""),
        })
    return events


def get_keep_notes():
    """Fetch Keep notes created in the last week or with upcoming reminders."""
    if not GOOGLE_APP_PASS:
        return []
    keep = gkeepapi.Keep()
    keep.login(GOOGLE_EMAIL, GOOGLE_APP_PASS)
    keep.sync()

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    notes = []
    for note in keep.all():
        if note.trashed or note.archived:
            continue

        has_upcoming_reminder = False
        reminder_dt = None
        try:
            for reminder in (note.reminders or []):
                dt = reminder.dt
                if dt:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt > now:
                        has_upcoming_reminder = True
                        reminder_dt = dt.strftime("%a %d/%m %H:%M")
                        break
        except Exception:
            pass

        created = note.timestamps.created
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created_recently = created and created >= week_ago

        if not created_recently and not has_upcoming_reminder and not note.pinned:
            continue

        if isinstance(note, gkeepapi.node.Note):
            text_content = note.text[:500]
        elif isinstance(note, gkeepapi.node.List):
            lines = [f"☐ {item.text}" for item in note.items if not item.checked]
            text_content = "\n".join(lines)
        else:
            continue

        if text_content.strip():
            entry = {
                "title":   note.title or "(untitled)",
                "pinned":  note.pinned,
                "content": text_content,
                "updated": str(note.timestamps.updated),
            }
            if reminder_dt:
                entry["reminder"] = reminder_dt
            notes.append(entry)

    notes.sort(key=lambda n: (not n["pinned"], not n.get("reminder"), n["updated"]), reverse=False)
    return notes[:10]


def get_notion_tests():
    """Query the Tests database for upcoming tests (due date >= today)."""
    if not NOTION_TESTS_DB_ID:
        return []
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    today_str = datetime.now().date().isoformat()
    payload = {
        "filter": {
            "property": "Due date",
            "date": {"on_or_after": today_str}
        },
        "sorts": [{"property": "Due date", "direction": "ascending"}],
        "page_size": 20,
    }
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_TESTS_DB_ID}/query",
        headers=headers,
        json=payload,
        timeout=10,
    )
    tests = []
    for page in r.json().get("results", []):
        props = page.get("properties", {})

        title = "(untitled)"
        for prop in props.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                title_list = prop.get("title", [])
                if title_list:
                    title = title_list[0]["plain_text"]
                break

        due_prop = props.get("Due date") or props.get("Due") or {}
        due = (due_prop.get("date") or {}).get("start", "")

        if title and due:
            page_id = page.get("id", "")
            description = ""
            if page_id:
                rb = requests.get(
                    f"https://api.notion.com/v1/blocks/{page_id}/children",
                    headers=headers,
                    timeout=10,
                )
                lines = []
                for block in rb.json().get("results", []):
                    btype = block.get("type", "")
                    rich = block.get(btype, {}).get("rich_text", [])
                    text = "".join(t.get("plain_text", "") for t in rich)
                    if text.strip():
                        lines.append(text.strip())
                description = " | ".join(lines[:5])

            tests.append({"subject": title, "due": due, "description": description})

    return tests


def get_notion_content():
    """Search all of Notion for relevant content + read any extra pages."""
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    results = []

    search_queries = ["test", "zkoušení", "úkol", "homework", "deadline"]
    seen_ids = set()
    for query in search_queries:
        r = requests.post(
            "https://api.notion.com/v1/search",
            headers=headers,
            json={"query": query, "page_size": 10},
            timeout=10,
        )
        for page in r.json().get("results", []):
            pid = page.get("id", "")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                title_prop = (
                    page.get("properties", {}).get("title", {}).get("title", [])
                    or page.get("properties", {}).get("Name", {}).get("title", [])
                )
                title = title_prop[0]["plain_text"] if title_prop else page.get("url", "")
                results.append({"source": "search", "title": title, "id": pid})

    all_content = {}
    page_ids = list(seen_ids) + [p for p in NOTION_EXTRA_PAGES if p not in seen_ids]
    for pid in page_ids[:8]:
        r = requests.get(
            f"https://api.notion.com/v1/blocks/{pid}/children",
            headers=headers,
            timeout=10,
        )
        blocks = r.json().get("results", [])
        lines = []
        for block in blocks:
            btype = block.get("type", "")
            rich = block.get(btype, {}).get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in rich)
            if text.strip():
                lines.append(text.strip())
        if lines:
            label = next((x["title"] for x in results if x["id"] == pid), pid)
            all_content[label] = lines[:20]

    return all_content


def send_ntfy(topic, title, body):
    requests.post(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title":    title.encode("utf-8"),
            "Priority": "default",
            "Tags":     "sunny,memo",
        },
        timeout=10,
    )


def main():
    creds   = get_google_creds()
    gmail   = build("gmail",    "v1", credentials=creds)
    cal     = build("calendar", "v3", credentials=creds)

    emails       = get_emails(gmail)
    events       = get_calendar(cal)
    keep_notes   = get_keep_notes()
    notion_data  = get_notion_content()
    notion_tests = get_notion_tests()

    today = datetime.now().strftime("%A, %B %d, %Y")
    now_date = datetime.now().date()
    school_days = []
    d = now_date + timedelta(days=1)
    while len(school_days) < 5:
        if d.weekday() < 5:
            school_days.append(d.strftime("%A %d/%m"))
        d += timedelta(days=1)
    forward_week = ", ".join(school_days)

    data_blob = json.dumps({
        "date":           today,
        "emails":         emails,
        "calendar":       events,
        "keep_notes":     keep_notes,
        "notion_content": notion_data,
        "upcoming_tests": notion_tests,
    }, indent=2, ensure_ascii=False)

    prompt = f"""You are generating Adrian's morning briefing. Adrian is a high school student. Be concise — this is a phone notification. Write each section in the same language the content is written in.

Today is {today}. The next 5 school days are: {forward_week}.

Structure (use these exact headers):
📧 EMAILS
Only emails needing a human response. Skip automated alerts, newsletters, receipts. Max 4 items. One line each: "From — Subject"

📅 TODAY
Chronological schedule, one line per event: "HH:MM–HH:MM  Title  (location if any)"
Use 24h time. If no events, say "No events today."

📝 KEEP
Show notes from the last 7 days and any with upcoming reminders (show reminder time if present). Pinned notes always shown. Max 5 items.

📚 UPCOMING TESTS
Use the "upcoming_tests" field — these are already filtered to future dates only.
List ALL of them. Format each as: "Subject — Date (description if any)"
Sort by date. If empty, say "No upcoming tests."

✅ TASKS
Top 3 priorities from Notion. Flag overdue (🔴) or due soon (⚠️). Skip if no data.

🎯 FOCUS
One sentence: the single most important thing to do today.

Keep the whole briefing under 400 words.

Data:
{data_blob}
"""

    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    briefing = response.content[0].text

    send_ntfy(NTFY_TOPIC, f"☀️ Morning Briefing — {datetime.now().strftime('%a %d/%m')}", briefing)
    print("Sent!")
    print(briefing)


if __name__ == "__main__":
    main()
