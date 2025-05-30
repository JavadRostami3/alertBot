import os
import asyncio
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError, rpcerrorlist
from telethon.errors import PhoneCodeEmptyError, PhoneCodeExpiredError, PasswordHashInvalidError
from telethon.tl.functions.channels import JoinChannelRequest
from telegram.ext import Updater, MessageHandler, Filters
from telegram import WebhookInfo

from config_validator import ConfigValidator
from session_handler import SessionHandler
from message_processor import MessageProcessor
from logger_config import setup_logger
from ui_bot_handler import get_phone_number_from_bot, get_code_from_bot, user_response, response_event
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
        if self._auth_in_progress:
            logger.warning("Authentication process already in progress.")
            return

        self._auth_in_progress = True
        try:
            # Attempt to start the client. This might trigger auth prompts.
            await self.client.start()
            logger.info("Initial client start successful (might be resumed session).")

            if not await self.client.is_user_authorized():
                 logger.info("Client is not authorized. Starting interactive authentication.")
                 # Initiate the authentication flow.
                 # First, request the phone number if needed.
                 # Telethon's sign_in will likely raise an exception if phone is needed or code is needed.
                 try:
                     # Try signing in. This will raise an error if phone/code/password is needed.
                     await self.client.sign_in(password='dummy') # Use a dummy password to trigger SessionPasswordNeededError if 2FA is on
                 except (SessionPasswordNeededError, PhoneCodeEmptyError, PhoneCodeExpiredError, PasswordHashInvalidError) as e:
                      logger.info(f"Telethon requires authentication input: {type(e).__name__}")

                      # Handle phone code request
                      if isinstance(e, (PhoneCodeEmptyError, PhoneCodeExpiredError)):
                           logger.info("Requesting phone code via UI bot...")
                           # We need the phone number first if not already available in the session
                           # The telethon client object should have the disconnected_phone if start was called without auth
                           phone_number = await get_phone_number_from_bot()
                           await self.client.send_code_request(phone_number)
                           logger.info("Phone code request sent. Requesting code via UI bot...")
                           code = await get_code_from_bot()
                           # Now sign in with phone and code
                           await self.client.sign_in(phone_number, code)
                           logger.info("Signed in with phone and code.")

                      # Handle 2FA password request
                      elif isinstance(e, SessionPasswordNeededError):
                           logger.warning("Two-factor authentication is enabled.")
                           # You need to implement get_password_from_bot in ui_bot_handler.py
                           # password = await get_password_from_bot()
                           # await self.client.sign_in(password=password)
                           logger.error("2FA password required. Please disable it or implement password handler.")
                           # Depending on your requirements, you might want to exit here
                           # raise e # Re-raise to stop the bot if 2FA is unhandled

                      elif isinstance(e, PasswordHashInvalidError):
                          logger.error("Invalid password provided for 2FA.")
                          # Handle invalid password (e.g., ask again)

                 if await self.client.is_user_authorized():
                     logger.info("User authorized successfully after interactive flow.")
                 else:
                     logger.error("Authentication failed after interactive flow.")
                     # Depending on your requirements, you might want to stop the bot here
                     return False # Indicate auth failure

            # Check authorization status after all attempts
            if not await self.client.is_user_authorized():
                 logger.error("Telethon client failed to authorize user.")
                 return False # Indicate failure

            return True # Indicate success

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
            
            # Handle authentication interactively
            if not await self.authenticate():
                 logger.error("Authentication failed. Stopping bot.")
                 return False # Stop if authentication fails

            # Log authorization status after authentication attempt
            if await self.client.is_user_authorized():
                 logger.info("Telethon client is authorized.")
            else:
                 logger.warning("Telethon client is NOT authorized after authentication process.")

            
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
            # This catch is a fallback, ideally the authenticate method handles it
            logger.error("SessionPasswordNeededError escaped authentication handler. 2FA likely not handled.")
            return False
        except Exception as e:
            logger.error(f"Critical error in Telegram client startup: {e}")
            return False
        finally:
            self.is_running = False
            if self.client and self.client.is_connected(): # Check if client exists and is connected before disconnecting
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

# --- UI Bot Handler (Webhook) --- #
async def handle_ui_bot_message(update, context):
    """Handler for messages received by the UI bot."""
    global user_response
    global response_event

    chat_id = os.getenv('CHAT_ID')
    if not chat_id:
        logger.error("CHAT_ID not found in environment variables for UI bot handler.")
        # Send a message back to the user indicating configuration error
        if update.effective_chat:
             try:
                 await context.bot.send_message(chat_id=update.effective_chat.id, text="Bot configuration error: CHAT_ID not set.")
             except Exception as send_e:
                 logger.error(f"Error sending config error message: {send_e}")
        return

    # Only process messages from the designated chat ID
    if str(update.effective_chat.id) == chat_id:
        user_response = update.message.text
        response_event.set()
        logger.info(f"Received UI bot message from {chat_id}: {user_response}")
        # Optionally send a confirmation back to the user
        # try:
        #     await context.bot.send_message(chat_id=chat_id, text="Received your input.")
        # except Exception as send_e:
        #      logger.error(f"Error sending confirmation message: {send_e}")

    else:
        logger.warning(f"Received UI bot message from unexpected chat ID: {update.effective_chat.id}")
        # Send a message back to the unexpected chat
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Unauthorized access.")
        except Exception as e:
             logger.error(f"Error sending unauthorized access message: {e}")


async def run_ui_bot():
    """Runs the Telegram UI bot using Webhook for Render deployment."""
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("BOT_TOKEN not found in environment variables. Cannot run UI bot.")
        return # Exit if no bot token

    render_external_url = os.getenv('RENDER_EXTERNAL_URL')
    # Safely get port, default to None if not set or invalid, for webhook config
    try:
        port = int(os.getenv('PORT'))
    except (ValueError, TypeError):
        logger.error("PORT environment variable is not set or is invalid.")
        # Depending on environment, you might need a default port or raise error
        # For Render web services, PORT is mandatory and should be injected.
        # If it's missing, webhook setup will fail.
        return # Exit if port is not set or invalid


    if not render_external_url:
        logger.error("RENDER_EXTERNAL_URL not found in environment variables. Cannot set up webhook.")
        # In a production environment like Render, this should ideally not happen.
        # Without a public URL, webhook cannot be set.
        # No fallback to polling here, as polling caused issues.
        return # Exit if URL is missing

    try:
        # Create the Application and pass it your bot token
        # Using ApplicationBuilder for modern python-telegram-bot async features
        from telegram.ext import ApplicationBuilder
        application = ApplicationBuilder().token(bot_token).build()

        # Get dispatcher to register handlers
        dispatcher = application.dispatcher

        # Add handler for all text messages from the specified chat ID
        dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_ui_bot_message))

        # Set the webhook
        webhook_path = '/webhook' # Define the URL path for the webhook
        webhook_url = render_external_url + webhook_path

        logger.info(f"Setting webhook to: {webhook_url} on port {port}")

        # Remove any existing webhook first (important for Render restarts)
        try:
            await application.bot.delete_webhook()
            await asyncio.sleep(1) # Give a moment for the delete to process
            logger.info("Existing webhook deleted.")
        except Exception as webhook_delete_error:
            logger.warning(f"Could not delete existing webhook (may not exist): {webhook_delete_error}")

        # Set the new webhook
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook successfully set to {webhook_url}")

        # Start the webhook server
        # The webhook server runs in a separate task managed by the Application
        # We need to run the Application until it is stopped.
        logger.info(f"Starting UI bot webhook server on port {port}...")
        # This should be the main async task for the UI bot
        await application.run_webhook(listen="0.0.0.0", port=port, webhook_url=webhook_url, url_path=webhook_path)

        logger.info("UI bot webhook server stopped.")

    except Exception as e:
        logger.error(f"Error running UI bot with webhook: {e}")
        # Re-raise the exception to potentially stop the main program
        raise e


async def main():
    """Main entry point"""
    # Load environment variables here as well to ensure they are available for both bots
    load_dotenv()

    # Get the event loop
    loop = asyncio.get_event_loop()

    # Create and run the Telethon bot in a task
    # Authentication is handled within the bot's start method
    telethon_bot = TelegramUIBot()
    telethon_bot_task = loop.create_task(telethon_bot.start())

    # Create and run the UI bot webhook server in a task
    # Use a try-except to catch exceptions from run_ui_bot and potentially stop telethon_bot
    ui_bot_task = None
    try:
        ui_bot_task = loop.create_task(run_ui_bot())

        # Wait for both tasks to complete (they are expected to run indefinitely)
        await asyncio.gather(telethon_bot_task, ui_bot_task)

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping bots...")
    except Exception as e:
        logger.error(f"Unexpected error in main gathering tasks: {e}. Attempting graceful shutdown.")
        # Propagate the error or handle it gracefully
        # The exception from run_ui_bot will stop that task.
        # We should ensure telethon_bot is also stopped.
        
    finally:
         # Cancel tasks gracefully on exit or error
         if telethon_bot_task and not telethon_bot_task.done():
             telethon_bot_task.cancel()
             logger.info("Telethon bot task cancelled.")
         if ui_bot_task and not ui_bot_task.done():
             ui_bot_task.cancel()
             logger.info("UI bot task cancelled.")

         # Wait for cancellation to complete
         # Use return_exceptions=True to prevent exceptions during cancellation from stopping gather
         try:
              await asyncio.gather(telethon_bot_task, ui_bot_task, return_exceptions=True)
              logger.info("Tasks gathered after cancellation.")
         except Exception as gather_e:
              logger.error(f"Error during final gather after cancellation: {gather_e}")

         # The finally block in TelegramUIBot.start() will handle client disconnect
         # and signal handler cleanup.


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
