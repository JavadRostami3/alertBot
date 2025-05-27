import os
import re
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
import google.generativeai as genai


def load_env_config():
    load_dotenv()
    return {
        'api_id': int(os.getenv('API_ID')),
        'api_hash': os.getenv('API_HASH'),
        'gemini_api_key': os.getenv('GEMINI_API_KEY'),
        'channels': os.getenv('CHANNELS', '').split(','),
        'cv_url': os.getenv('CV_URL'),
        'portfolio_url': os.getenv('PORTFOLIO_URL'),
        'proxy_type': os.getenv('PROXY_TYPE'),
        'proxy_server': os.getenv('PROXY_SERVER'),
        'proxy_port': os.getenv('PROXY_PORT'),
    }


def connect_telegram(api_id, api_hash, proxy_settings=None):
    if proxy_settings and proxy_settings['proxy_type'] and proxy_settings['proxy_server'] and proxy_settings['proxy_port']:
        proxy_type = proxy_settings['proxy_type'].lower()
        proxy_server = proxy_settings['proxy_server']
        try:
            proxy_port = int(proxy_settings['proxy_port'])
        except (ValueError, TypeError):
            print("خطا: پورت پروکسی نامعتبر است.")
            return TelegramClient('session', api_id, api_hash)

        if proxy_type == 'socks5':
             # For SOCKS5, proxy tuple is ('socks5', server, port, rdns, username, password)
             # Assuming no username/password for simplicity unless needed, rdns=True
             proxy = ('socks5', proxy_server, proxy_port, True) # rdns=True is common for SOCKS5
             print(f"اتصال از طریق پروکسی SOCKS5 به {proxy_server}:{proxy_port}")
             return TelegramClient('session', api_id, api_hash, proxy=proxy)
        # Add other proxy types if needed (HTTP, etc.)
        else:
            print(f"خطا: نوع پروکسی {proxy_type} پشتیبانی نمی‌شود. اتصال بدون پروکسی.")
            return TelegramClient('session', api_id, api_hash) # Connect without proxy
    else:
        print("اتصال بدون پروکسی.")
        return TelegramClient('session', api_id, api_hash)


def contains_ui_keywords(text):
    keywords = ['UI', 'UX', 'interface', 'figma', 'فرانت', 'طراحی رابط']
    return any(k.lower() in text.lower() for k in keywords)


def extract_username(text):
    match = re.search(r'@[\w\d_]+', text)
    return match.group(0) if match else None


async def generate_custom_message(text, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-pro')

    prompt = f"""با توجه به آگهی زیر، یک پیام حرفه‌ای، مودبانه و دوستانه به زبان فارسی برای اعلام آمادگی و ارسال پیشنهاد همکاری بنویس. در پیام حتما به صورت خلاصه به تجربه مرتبط خودت اشاره کن و اشتیاقت رو برای همکاری نشون بده. پیام نباید خیلی طولانی باشه و بهتره با یک ایموجی مناسب شروع بشه و با یک ایموجی مناسب تموم بشه.

متن آگهی:
{text}
"""

    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e:
        print(f"خطا در ارتباط با Gemini API: {e}")
        return "متاسفانه در حال حاضر امکان تولید پیام خودکار وجود ندارد. لطفا بعدا تلاش کنید."


async def send_message_to_user(client, username, message, portfolio_url, cv_filename="javad-rostami resume.pdf"):
    entity = await client.get_entity(username)

    # ارسال پیام متنی
    await client.send_message(entity, message)

    # ارسال فایل رزومه
    cv_path = os.path.join(os.path.dirname(__file__), cv_filename)
    if os.path.exists(cv_path):
        try:
            await client.send_file(entity, cv_path, caption=f"فایل رزومه اینجانب.\nنمونه‌کار: {portfolio_url}")
            print(f"رزومه با موفقیت برای {username} ارسال شد.")
        except Exception as e:
            print(f"خطا در ارسال فایل رزومه به {username}: {e}")
            await client.send_message(entity, f"(خطا در ارسال فایل رزومه. لینک نمونه کار: {portfolio_url})")
    else:
        print(f"فایل رزومه در مسیر {cv_path} یافت نشد.")
        await client.send_message(entity, f"(فایل رزومه یافت نشد. لینک نمونه کار: {portfolio_url})")


async def fetch_channels(client, channels):
    """
    عضویت در کانال‌ها و بازگرداندن entityهای آن‌ها
    """
    entities = []
    for ch in channels:
        try:
            await client(JoinChannelRequest(ch))
        except Exception:
            pass
        try:
            entity = await client.get_entity(ch)
            entities.append(entity)
        except Exception as e:
            print(f"خطا در دریافت یا عضویت کانال {ch}: {e}")
    return entities


async def process_new_message(event, client, config):
    """پردازش پیام جدید: فیلتر کلیدواژه، استخراج یوزرنیم، تولید و ارسال پاسخ"""
    text = event.message.message
    if contains_ui_keywords(text):
        username = extract_username(text)
        if username:
            msg = await generate_custom_message(text, config['gemini_api_key'])
            await send_message_to_user(client, username, msg, config['portfolio_url'])


async def main():
    config = load_env_config()
    proxy_settings = {
        'proxy_type': config.get('proxy_type'),
        'proxy_server': config.get('proxy_server'),
        'proxy_port': config.get('proxy_port'),
    }
    client = connect_telegram(config['api_id'], config['api_hash'], proxy_settings=proxy_settings)

    # شروع جلسه و عضویت در کانال‌ها
    await client.start()
    channel_entities = await fetch_channels(client, config['channels'])

    @client.on(events.NewMessage(chats=channel_entities))
    async def handler(event):
        await process_new_message(event, client, config)

    print("Bot is running...")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
