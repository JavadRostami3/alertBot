# telegram-ui-agent

یک ربات تلگرامی هوشمند برای رصد آگهی‌های طراحی UI/UX و ارسال پیام شخصی‌سازی‌شده.

## پیش‌نیازها

- Python 3.10+
- حساب شخصی Telegram
- کلیدهای API

## نصب و راه‌اندازی

```bash
git clone https://github.com/yourusername/telegram-ui-agent.git
cd telegram-ui-agent
pip install -r requirements.txt
```

## تنظیم متغیرهای محیطی

در فایل `.env` متغیرهای زیر را پر کنید:

```
API_ID=...
API_HASH=...
GEMINI_API_KEY=...
CHANNELS=...
CV_URL=...
PORTFOLIO_URL=...
```

## اجرا

```bash
python main.py
```

## ساختار پروژه

```plaintext
telegram-ui-agent/
├── .env
├── main.py
├── requirements.txt
└── README.md
```

## توابع اصلی

- load_env_config()
- connect_telegram()
- fetch_channels()
- process_new_message(event)
- contains_ui_keywords(text)
- extract_username(text)
- generate_custom_message(text)
- send_message_to_user(username, message)
