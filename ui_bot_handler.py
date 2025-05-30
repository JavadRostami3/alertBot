import os
import logging
from telegram import Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import asyncio

logger = logging.getLogger(__name__)

# Use a global variable to store the user's response
user_response = None
response_event = asyncio.Event()

async def send_telegram_message(token: str, chat_id: str, message: str):
    """Sends a message to a specific chat ID using the provided bot token."""
    try:
        bot = Bot(token)
        # Note: Use bot.send_message directly without Updater for simple cases
        # or integrate with an existing Updater/Dispatcher setup.
        await bot.send_message(chat_id=chat_id, text=message)
        logger.info(f"Message sent to chat ID {chat_id}")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")

async def request_input_via_bot(token: str, chat_id: str, prompt: str) -> str:
    """Sends a prompt via bot and waits for the user's response."""
    global user_response
    global response_event

    user_response = None
    response_event.clear()

    await send_telegram_message(token, chat_id, prompt)

    logger.info(f"Waiting for user response to: {prompt}")
    await response_event.wait() # Wait until the response_event is set

    return user_response

# Placeholder for handling incoming messages to the UI bot token.
# This part needs to be implemented elsewhere to receive messages
# from the user (via CHAT_ID) and update the `user_response` and
# set the `response_event` accordingly.
# Example handler structure:
# async def handle_user_response(update, context):
#     global user_response
#     global response_event
#     if str(update.effective_chat.id) == os.getenv('CHAT_ID'):
#         user_response = update.message.text
#         response_event.set()
#         logger.info(f"Received user response: {user_response}")
#     else:
#         logger.warning(f"Received message from unexpected chat ID: {update.effective_chat.id}")

# Functions that telethon can call to get user input
async def get_phone_number_from_bot():
    token = os.getenv('BOT_TOKEN')
    chat_id = os.getenv('CHAT_ID')
    if not token or not chat_id:
        logger.error("BOT_TOKEN or CHAT_ID not found in environment variables.")
        raise ValueError("BOT_TOKEN or CHAT_ID not configured.")

    prompt = "لطفاً شماره تلفن خود را برای ورود به تلگرام وارد کنید:"
    phone_number = await request_input_via_bot(token, chat_id, prompt)
    return phone_number

async def get_code_from_bot():
    token = os.getenv('BOT_TOKEN')
    chat_id = os.getenv('CHAT_ID')
    if not token or not chat_id:
        logger.error("BOT_TOKEN or CHAT_ID not found in environment variables.")
        raise ValueError("BOT_TOKEN or CHAT_ID not configured.")

    prompt = "لطفاً کد تاییدی که از تلگرام دریافت کرده‌اید را وارد کنید:"
    code = await request_input_via_bot(token, chat_id, prompt)
    return code

# Optional: Function to handle 2FA password if enabled
# async def get_password_from_bot():
#     token = os.getenv('BOT_TOKEN')
#     chat_id = os.getenv('CHAT_ID')
#     if not token or not chat_id:
#         logger.error("BOT_TOKEN or CHAT_ID not found in environment variables.")
#         raise ValueError("BOT_TOKEN or CHAT_ID not configured.")
#
#     prompt = "لطفاً رمز عبور دو مرحله‌ای تلگرام خود را وارد کنید:"
#     password = await request_input_via_bot(token, chat_id, prompt)
#     return password 