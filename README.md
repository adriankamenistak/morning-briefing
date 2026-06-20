# Morning Briefing

A Python script that runs automatically every morning at 6 AM and sends a structured daily briefing to your phone via [ntfy](https://ntfy.sh).

## What it does

Every morning it pulls data from:

- **Gmail** — unread emails needing a response (last 24h)
- **Google Calendar** — today's and tomorrow's events
- **Google Keep** — pinned notes, notes from the last 7 days, and notes with upcoming reminders
- **Notion** — tasks and upcoming tests/exams from your school database

It then asks Claude (Haiku) to summarize everything into a concise briefing and pushes it to your phone as a push notification.

## Example output

```
📧 EMAILS
No emails requiring a response.

📅 TODAY
08:00–10:00  Call ctyrlistek
All day  10. Vyroci ctyrlistek  (Struhařov, Czechia)

📝 KEEP
☐ Buy train ticket for Saturday

📚 UPCOMING TESTS
Čj syntax — Tuesday 09/06
Čtvrtletka matika — Tuesday 09/06 (Similarity onwards)
Děják — Wednesday 10/06 (ČSR 1945–1989)

✅ TASKS
No tasks found.

🎯 FOCUS
Review Czech syntax and math similarity before Tuesday's tests.
```

## Requirements

- Python 3.10+
- Windows (uses Task Scheduler for automation)
- Google account (Gmail + Calendar + Keep)
- Notion account
- Anthropic API key
- ntfy app on your phone

## Setup

### 1. Install dependencies

```
pip install anthropic gkeepapi google-auth google-auth-oauthlib google-api-python-client requests
```

### 2. Google API

1. Go to [Google Cloud Console](https://console.cloud.google.com) and create a project
2. Enable **Gmail API** and **Google Calendar API**
3. Create OAuth credentials (Desktop app) and download as `credentials.json` into this folder
4. Add your email as a test user in the OAuth consent screen

### 3. Google App Password (for Keep)

1. Enable 2-step verification on your Google account
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an app password named `MorningBriefing`

### 4. Notion

1. Go to [app.notion.com/developers](https://app.notion.com/developers) → Personal access tokens → create one
2. Get your Tests database ID from the Notion URL (the part after `/p/` before `?v=`)

### 5. Anthropic API key

Get one at [console.anthropic.com](https://console.anthropic.com)

### 6. ntfy

1. Install the ntfy app on your phone
2. Subscribe to a topic (e.g. `your-name-briefing-1234`)

### 7. Create config.py

Create a `config.py` file in the same folder (this file is gitignored — never commit it):

```python
ANTHROPIC_API_KEY  = "your-anthropic-api-key"
NOTION_API_KEY     = "your-notion-api-key"
NOTION_TESTS_DB_ID = "your-tests-db-id"
NTFY_TOPIC         = "your-topic-name"
GOOGLE_EMAIL       = "you@example.com"
GOOGLE_APP_PASS    = "your-app-password"

# Optional: add Notion page IDs to always include
NOTION_EXTRA_PAGES = [
    "your-page-id",
]
```

### 8. First run

Run manually once to authorize Google:

```
python morning_briefing.py
```

A browser will open for Google login. After that, `token.pickle` is created and future runs are fully automatic.

### 9. Schedule with Windows Task Scheduler

1. Open Task Scheduler → Create Basic Task
2. Trigger: Daily at 6:00 AM
3. Action: Start a program
   - Program: `C:\Users\YourName\AppData\Local\Programs\Python\Python3XX\python.exe`
   - Arguments: `C:\Users\YourName\MorningBriefing\morning_briefing.py`
4. In Properties → Conditions: check "Wake the computer to run this task"
5. In Properties → Settings: check "Run task as soon as possible after a scheduled start is missed"

## Files

| File                  | Description                                                  |
| --------------------- | ------------------------------------------------------------ |
| `morning_briefing.py` | Main script                                                  |
| `credentials.json`    | Google OAuth credentials (not committed)                     |
| `token.pickle`        | Google auth token, auto-created on first run (not committed) |

## Notes

- `credentials.json` and `token.pickle` are excluded from git — never commit these
- Rotate your API keys if you ever share them publicly
- Google Keep access uses the unofficial [gkeepapi](https://github.com/kiwiz/gkeepapi) library
