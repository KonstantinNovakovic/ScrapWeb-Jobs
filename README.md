# ScrapWeb-Jobs

Python utility that checks job listings on **poslovi.infostud.com**, filters them by your keywords/location, remembers already seen jobs, and sends only new matches to Telegram.

Runs well as a local cron task every 4 hours on Kubuntu/Linux.

## Features

- Scrapes Infostud jobs (with a "RSS-first, HTML-fallback" strategy)
- Case-insensitive filtering by include/exclude keywords and location
- Deduplication using `seen_jobs.json`
- Telegram notifications for new jobs only
- Silent if no new matching jobs
- Config-driven (`config.json`) with no hardcoded credentials

## Project structure

```text
ScrapWeb-Jobs/
├── main.py
├── config.example.json
├── requirements.txt
├── README.md
├── .gitignore
└── src/
    ├── __init__.py
    ├── scraper.py
    ├── filter.py
    ├── storage.py
    └── notifier.py
```

## 1) Install dependencies

```bash
cd /path/to/ScrapWeb-Jobs
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Configure the app

Create your runtime config from example:

```bash
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "keywords": ["customer support", "QA", "junior frontend", "tester", "help desk", "english"],
  "exclude_keywords": ["senior", "internship"],
  "location": "Beograd",
  "sites": ["infostud"],
  "telegram_token": "YOUR_BOT_TOKEN_HERE",
  "chat_id": "YOUR_CHAT_ID_HERE"
}
```

`config.json` is ignored by git.

## 3) Telegram bot setup (BotFather)

1. Open Telegram and find **@BotFather**.
2. Send `/newbot` and follow prompts.
3. Copy generated bot token into `telegram_token`.

### Get your `chat_id`

Option A (quick):
1. Send any message to your bot.
2. Open in browser:
   - `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. Find `message.chat.id` in JSON response.
4. Put it into `chat_id`.

Option B: add bot to a group, send a message, and read group chat id from `getUpdates`.

## 4) Run manually

```bash
./run.sh
```

Pipeline:

1. scrape
2. filter
3. deduplicate (seen IDs)
4. notify on Telegram

If there are no new matches, the script exits quietly.

## 5) Cron setup (every 4 hours)

Edit crontab:

```bash
crontab -e
```

Example line (every 4 hours):

```cron
0 */4 * * * /home/kosta/repos/ScrapWeb-Jobs/run.sh >> /home/kosta/repos/ScrapWeb-Jobs/cron.log 2>&1
```

## Notes on scraping reliability

- Infostud structure can change over time.
- The scraper uses a respectful `User-Agent` and delay during RSS discovery.
- If scraping fails, you'll get a clear log error instead of a silent crash.
- Code is organized so adding new sites later is straightforward (add another scraper class and hook it in `main.py`).
