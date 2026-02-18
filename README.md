# Automation for tenant consumption values

Automated Python application that scrapes utility consumption data from the HomeCase portal, stores it in PostgreSQL, and sends formatted email notifications to tenants.
Currently supports only one HomeCase message stream and one tenant recipient flow.

⚠️ **Disclaimer**

This project is an independent, open-source tool and is **not affiliated with, endorsed by, or associated with HomeCase or its parent companies**.

- **Use at your own risk:** Automating interactions with web portals may violate their Terms of Service (AGB). Using this tool could potentially lead to your account being restricted or banned by the provider.
- **No Warranty:** The software is provided "as is", without warranty of any kind. The authors are not liable for any damages, data loss, or legal consequences arising from the use of this tool.
- **Data Privacy:** This tool processes personal data. It is the sole responsibility of the user to ensure compliance with applicable data protection laws (e.g., GDPR/DSGVO) when storing and processing tenant data.


## Quick Start

**Prerequisites:** Python 3.10+, external PostgreSQL database instance, SMTP credentials, HomeCase portal credentials

```bash
# Optional: create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
python -m src.main
```

## Configuration

**Required environment variables:**
- `HOMECASE_URL_LOGIN`: Login URL
- `HOMECASE_URL_MESSAGES`: Message stream URL
- `HOMECASE_USERNAME`: Portal username
- `HOMECASE_PASSWORD`: Portal password
- `DATABASE_URL`: PostgreSQL connection string (`postgresql://user:password@host:port/database`)
- `SMTP_HOST`: SMTP server hostname
- `SMTP_PORT`: SMTP port (587 for STARTTLS, 465 for SSL/TLS)
- `SMTP_USER`: SMTP username
- `SMTP_PASSWORD`: SMTP password
- `EMAIL_FROM`: Sender email address
- `EMAIL_TO`: Comma-separated recipient list

**Optional:**
- `DATABASE_SCHEMA`: Database schema name (default: `public`)
- `TENANT_GREETING`: Email greeting text (default: `Liebe Mieterin`)
- `EMAIL_SIGNATURE`: Email signature text (will be appended to email body if provided). Use `\n` for line breaks.
- `EMAIL_TO_CC`: Comma-separated list of CC recipients
- `REQUEST_DELAY_SECONDS`: Pause between HomeCase HTTP requests in seconds (default: `0.5`)
- `LOG_LEVEL`: Logging level (default: `INFO`)
- `LOG_FILE`: Path to log file (default: stderr)

## Why this exists

In Germany, landlords need to send these consumption values to tenants. Without this automation, that process would need to be done manually by email.

## Current limitations

- Only one HomeCase message stream is supported.
- Only one tenant recipient flow is supported.

**Planned improvements:**
- Add support for multiple message streams.
- Add support for multiple tenants/recipient groups.

## Architecture

**Workflow:**
1. Authenticate to HomeCase portal (extracts antiforgery token, performs JSON login)
2. Fetch consumption messages via BFF API (falls back to HTML parsing if API fails)
3. Parse messages to extract Kaltwasser, Warmwasser, and Heizung consumption values
4. Check idempotency via content hash (SHA256 of raw message)
5. Save new messages to PostgreSQL (JSONB storage for parsed data)
6. Send formatted email notifications via SMTP

**Components:**
- `scraper.py`: Web scraping (requests/BeautifulSoup), API client, HTML fallback
- `parser.py`: Regex-based extraction of consumption values and metadata
- `database.py`: PostgreSQL operations with connection pooling, auto-creates schema/table
- `email.py`: SMTP sending with TLS/STARTTLS support, German number formatting
- `models.py`: Pydantic models for type safety and validation

**Database Schema:**
- Table: `consumption_messages` (id, content_hash UNIQUE, message_date, raw_message TEXT, parsed_data JSONB, created_at)
- Indexes: content_hash, message_date
- Schema: configurable via `DATABASE_SCHEMA` (default: `public`)

## Execution

**Local:**
```bash
python -m src.main
```

**Docker:**
```bash
docker build -t unofficial-homecase-automation .
docker run --rm --env-file .env unofficial-homecase-automation
```

Alternatively, you can import and call the main function directly:
```python
from src.main import main
import sys
sys.exit(main())
```

**Exit Codes:**
- `0`: Success - new messages processed and emails sent
- `1`: Error - check logs for details
- `2`: No new messages - all fetched messages were already processed (idempotency)

**Scheduling:**
```cron
# Daily at 9 AM
0 9 * * * cd /path/to/project && python -m src.main
```

## Troubleshooting

- **Login fails:** Verify `HOMECASE_USERNAME`/`HOMECASE_PASSWORD` and check portal login form structure
- **Message not found:** Verify `HOMECASE_URL_MESSAGES` is accessible after login
- **Database errors:** Ensure PostgreSQL is running and `DATABASE_URL` is correct; auto-creation requires appropriate permissions
- **Email not sent:** Verify SMTP credentials and server accessibility


## License

MIT. See `LICENSE`.
