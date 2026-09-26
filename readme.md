# Dynamic Email Automation

A command-line tool that generates and sends personalized event/campaign emails to a list of recipients. You give it an Excel file of registrants and a plain-English prompt describing the campaign (e.g. event name, date, venue), and it:

1. Extracts recipient names and emails from the spreadsheet
2. Uses a local LLM (via [Ollama](https://ollama.com)) to write a personalized HTML email + subject line for each recipient
3. Sends the emails over SMTP, optionally with a file attachment
4. Logs every step to `app.log`

## How it works

```
app.py
  └─ pipeline/emailPipeline.py     orchestrates the run
       ├─ core/userDetailsExtractor.py   reads the Excel file → list of User
       ├─ core/email_content_generator.py  calls Ollama per user → Content (subject + HTML)
       └─ core/send_email.py             sends each email over SMTP
```

- **Extraction** (`userDetailsExtractor.py`): reads the given `.xlsx` with pandas, auto-detects the name and email columns (any column containing "name" / "email" in its header, case-insensitive), and drops fully empty rows.
- **Content generation** (`email_content_generator.py`): sends your campaign prompt + each recipient's name/email to a local `qwen2.5-coder:1.5b` model through Ollama, with strict formatting rules (plain HTML only, no placeholders like `[Insert Date]`, no spammy language, fixed sign-off). It retries up to 3 times (lowering the temperature after the first attempt) if the model's output fails validation or can't be parsed. A user is skipped (not sent to) if all 3 attempts fail.
- **Sending** (`send_email.py`): sends each generated email via Gmail's SMTP server (`smtp.gmail.com:587`, STARTTLS), optionally attaching a file. Results (success/failure) are written to the log per recipient. Two sets of sender credentials are supported so you can spread sends across two accounts once the first passes `limit_for_each_mail`.

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed and running locally, with the model pulled:
  ```
  ollama pull qwen2.5-coder:1.5b
  ```
  Verify it's running with `curl http://127.0.0.1:11434/api/tags`.
- A Gmail account with an **App Password** (requires 2-Step Verification enabled on the account). Regular Gmail passwords will not work over SMTP.

## Installation

```bash
git clone <this-repo>
cd Email_automation
pip install pandas openpyxl pydantic pydantic-settings python-dotenv ollama
```

## Configuration

Copy `.env.example` to `.env` and fill in your sender credentials:

```
userId1 = your_gmail_address@gmail.com
password1 = your16charapppassword
userId2 =
password2 =
```

- `userId1` / `password1` are required — this is the primary sending account.
- `userId2` / `password2` are optional, used only once a run exceeds `limit_for_each_mail` (default 150) recipients, to split volume across a second account.
- `.env` is git-ignored — never commit real credentials.

## Input spreadsheet format

An `.xlsx` file with at least two columns whose headers contain the substrings `name` and `email` (any casing, e.g. "Full Name", "Email Address"). One row per recipient.

## Usage

```bash
python3 app.py --excel test_registrations.xlsx --prompt "Welcome email for Incognito 5.0, Oct 10th, Main Auditorium"
```

Options:

| Flag | Required | Description |
|---|---|---|
| `--excel` | Yes | Path to the registrations `.xlsx` file |
| `--prompt` | Yes | Campaign instructions used to generate the email content (event name, date, venue, tone, etc.) |
| `--attachment` | No | Path to a file to attach to every email (e.g. a PDF flyer) |

## Logging

All runs append to `app.log` in the working directory (extraction counts, per-user generation attempts, send results). Tail it live while a run is in progress:

```bash
tail -f app.log
```

## Troubleshooting

- **`ModuleNotFoundError: No module named 'openpyxl'`** — install it: `pip install openpyxl`.
- **`SMTPAuthenticationError: (535, '5.7.8 Authentication failed')`** — usually means `userId1`/`password1` in `.env` don't match a valid Gmail App Password for that account, or 2-Step Verification isn't enabled.
- **Validation failed / placeholder text in output** — the local model occasionally returns text like `[Insert Date]`; the pipeline automatically retries (up to 3 attempts) and skips the recipient if all attempts fail. Check `app.log` for which users were skipped.
- **Nothing happening / no new log lines** — confirm Ollama is running and the `qwen2.5-coder:1.5b` model is pulled; content generation calls it for every recipient and will fail per-attempt if it's unreachable.

## Notes / limitations

- Emails are sent one at a time, synchronously — large recipient lists will take a while (each one needs an LLM call plus an SMTP round trip).
- There is currently no dry-run/preview mode; generated content is sent immediately once validated.
- No retry is attempted on SMTP send failures (only on content generation).