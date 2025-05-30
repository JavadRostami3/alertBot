import os
import asyncio
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError, rpcerrorlist
from telethon.errors import PhoneCodeEmptyError, PhoneCodeExpiredError, PasswordHashInvalidError
from telethon.tl.functions.channels import JoinChannelRequest
from flask_app import run_flask_app
from telegram import Bot as TgBot

from config_validator import ConfigValidator
from session_handler import SessionHandler
from message_processor import MessageProcessor
from logger_config import setup_logger
from ui_bot_handler import get_phone_number_from_bot, get_code_from_bot
import signal

# Setup logging
logger = setup_logger()

class TelegramUIBot:
    def __init__(self):
        self.config = None
        self.client = None
        self.session_handler = None
        self.message_processor = None
        self.channel_entities = []
        self.is_running = False
        # Flag to manage auth process status
        self._auth_in_progress = False
        
    async def initialize(self):
        """Initialize the bot with configuration and validation"""
        try:
            # Load and validate configuration
            load_dotenv()
            validator = ConfigValidator()
            self.config = validator.validate_config()
            logger.info("Configuration loaded and validated successfully")

            # Check for essential config for UI bot interaction
            if not os.getenv('BOT_TOKEN') or not os.getenv('CHAT_ID'):
                 logger.error("BOT_TOKEN or CHAT_ID not set in environment variables. UI bot interaction will not work.")
                 # Decide how to proceed if UI bot is essential - maybe raise an error?
                 # For now, log and continue, but auth may fail without UI bot.

            
            # Initialize session handler
            self.session_handler = SessionHandler(self.config)
            self.client = await self.session_handler.create_client()

            # No need to setup RpcError handler globally if we catch specific exceptions
            # self.setup_auth_handlers() # Removed this call
            
            # Initialize message processor
            self.message_processor = MessageProcessor(self.config)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False

    # Removed the setup_auth_handlers method as we'll use try/except in start()
    # async def setup_auth_handlers(self):
    #     ...

    async def authenticate(self):
        """Handles the Telethon authentication flow interactively via UI bot."""
        self._auth_in_progress = True
        try:
            # Connect the Telegram client using existing session or raw connection
            await self.client.connect()
            logger.info("Telethon client connected.")

            # If not authorized, start interactive phone+code login
            if not await self.client.is_user_authorized():
                logger.info("Client is not authorized. Starting interactive authentication.")
                phone_number = await get_phone_number_from_bot()
                await self.client.send_code_request(phone_number)
                logger.info("Phone code request sent. Waiting for code via UI bot...")
                code = await get_code_from_bot()
                # Sign in with the received code
                await self.client.sign_in(phone=phone_number, code=code)
                logger.info("Signed in with phone and code.")

            # Final authorization check
            if await self.client.is_user_authorized():
                logger.info("User successfully authorized.")
                return True
            else:
                logger.error("Authentication failed. Client still not authorized.")
                return False
        except SessionPasswordNeededError:
            logger.error("Two-factor authentication is enabled but not implemented in UI bot. Please disable 2FA or implement password flow.")
            return False
        except Exception as e:
            logger.error(f"Error during authentication process: {e}")
            return False
        finally:
            self._auth_in_progress = False

    async def join_channels(self):
        """Join all configured channels and return their entities"""
        entities = []
        for channel in self.config['channels']:
            if not channel.strip():
                continue
                
            try:
                # Try to join the channel first
                try:
                    await self.client(JoinChannelRequest(channel))
                    logger.info(f"Successfully joined channel: {channel}")
                except Exception as join_error:
                    logger.warning(f"Could not join channel {channel}: {join_error}")
                
                # Get channel entity
                entity = await self.client.get_entity(channel)
                entities.append(entity)
                logger.info(f"Added channel entity: {channel}")
                
            except Exception as e:
                logger.error(f"Failed to process channel {channel}: {e}")
                
        return entities
    
    async def setup_message_handler(self):
        """Setup the message event handler"""
        # Check if there are channels to monitor before setting up handler
        if not self.channel_entities:
            logger.warning("No valid channels to monitor. Skipping message handler setup.")
            return

        @self.client.on(events.NewMessage(chats=self.channel_entities))
        async def message_handler(event):
            try:
                await self.message_processor.process_message(event, self.client)
            except FloodWaitError as e:
                logger.warning(f"Rate limited, waiting {e.seconds} seconds")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"Error processing message: {e}")
        
        logger.info(f"Message handler setup for {len(self.channel_entities)} channels")
    
    async def start(self):
        """Start the bot"""
        try:
            if not await self.initialize():
                logger.error("Bot initialization failed")
                return False

            # Start and authorize the Telegram client using UI bot for phone & code
            await self.client.start(phone=get_phone_number_from_bot, code_callback=get_code_from_bot)
            logger.info("Telegram client started and authorized successfully")
            
            # Join channels
            self.channel_entities = await self.join_channels()
            # The check for empty channels is now in setup_message_handler

            # Setup message handler for incoming messages in joined channels
            await self.setup_message_handler()
            
            self.is_running = True
            logger.info("Bot is now running and monitoring channels...")
            
            # Keep the telethon client running until disconnected
            await self.client.run_until_disconnected()
            
        except SessionPasswordNeededError:
            logger.error("Two-factor authentication is enabled. Please disable it or implement get_password_from_bot.")
            return False
        except Exception as e:
            logger.error(f"Critical error in Telegram client startup: {e}")
            return False
        finally:
            self.is_running = False
            if self.client and self.client.is_connected():
                 await self.client.disconnect()
                 logger.info("Telethon client disconnected.")
            # Remove signal handlers upon exit
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)

    
    async def stop(self):
        """Gracefully stop the bot"""
        if self.is_running and self.client and self.client.is_connected():
            self.is_running = False
            await self.client.disconnect()
            logger.info("Telethon client stopped gracefully")
            # Note: UI bot (webhook) shutdown needs separate handling if not managed by updater.idle()
            # For webhook, stopping the underlying http server would be needed.
            # In this setup, the async sleep loop will just finish on task cancellation.

async def main():
    """Main entry point"""
    # Load environment variables
    load_dotenv()

    # Get the event loop
    loop = asyncio.get_event_loop()

    # Setup Telegram bot webhook manually
    bot_token = os.getenv("BOT_TOKEN")
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    port = int(os.getenv("PORT"))
    bot = TgBot(bot_token)
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=render_url + "/webhook")

    # Run Flask server in executor to handle webhook callbacks
    flask_task = loop.run_in_executor(
        None,
        run_flask_app,
        "0.0.0.0",
        port
    )

    # Run Telethon bot
    telethon_bot = TelegramUIBot()
    telethon_task = loop.create_task(telethon_bot.start())

    # Wait for both Flask and Telethon to run indefinitely
    await asyncio.gather(telethon_task, flask_task)


def shutdown_handler(signal_received, frame):
    logger.info(f'Signal {signal_received} received. Initiating graceful shutdown.')
    # Get the current event loop and stop it gracefully
    loop = asyncio.get_event_loop()
    # You might need a way to access the bot instance(s) here to call stop()
    # For simplicity now, we rely on the main loop cancellation and finally blocks
    # Or better, find the running tasks and cancel them:
    for task in asyncio.all_tasks(loop=loop):
        if task is not asyncio.current_task(loop=loop): # Don't cancel self
             task.cancel()
             logger.info(f"Cancelled task: {task.get_name() if hasattr(task, 'get_name') else task}")


if __name__ == '__main__':
    # Setup signal handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        # Get the current event loop or create a new one if none exists
        loop = asyncio.get_event_loop()
        if loop.is_running():
             logger.warning("Event loop is already running.")
             # If running in an environment like Jupyter, use run_until_complete
             # loop.run_until_complete(main())
             logger.error("Running in an unexpected async environment.")
             # Depending on context, you might need to raise an error or adapt.
             # For typical script execution, this block indicates an issue.
        else:
             # Otherwise, run the main coroutine
             logger.info("Starting main asyncio loop.")
             loop.run_until_complete(main())

    except KeyboardInterrupt:
        print("\nBot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        print(f"Fatal error in __main__: {e}")
        logger.error(f"Fatal error in __main__ block: {e}")
