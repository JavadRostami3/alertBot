import os
import asyncio
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.errors import rpcerrorlist
from telethon.tl.functions.channels import JoinChannelRequest
from telegram.ext import Updater, MessageHandler, Filters
from telegram import WebhookInfo

from config_validator import ConfigValidator
from session_handler import SessionHandler
from message_processor import MessageProcessor
from logger_config import setup_logger
from ui_bot_handler import get_phone_number_from_bot, get_code_from_bot, user_response, response_event

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
        
    async def initialize(self):
        """Initialize the bot with configuration and validation"""
        try:
            # Load and validate configuration
            load_dotenv()
            validator = ConfigValidator()
            self.config = validator.validate_config()
            logger.info("Configuration loaded and validated successfully")
            
            # Initialize session handler
            self.session_handler = SessionHandler(self.config)
            self.client = await self.session_handler.create_client()

            # Setup Telethon event handlers for authentication prompts
            await self.setup_auth_handlers()
            
            # Initialize message processor
            self.message_processor = MessageProcessor(self.config)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False

    async def setup_auth_handlers(self):
        """Setup event handlers for Telethon authentication prompts."""
        @self.client.on(events.RpcError)
        async def handle_auth_errors(event):
            # Use a flag to ensure we only handle one auth request at a time
            if hasattr(self, '_auth_in_progress') and self._auth_in_progress:
                return

            self._auth_in_progress = True
            try:
                if isinstance(event.original_event, rpcerrorlist.PhoneCodeEmptyError) or \
                   isinstance(event.original_event, rpcerrorlist.PhoneCodeExpiredError):
                    logger.warning("Telethon requested phone code.")
                    code = await get_code_from_bot()
                    await self.client.send_code_request(self.client.disconnected_phone, code)

                elif isinstance(event.original_event, rpcerrorlist.SessionPasswordNeededError):
                     logger.warning("Telethon requested 2FA password.")
                     # Assuming get_password_from_bot exists in ui_bot_handler.py if needed
                     # password = await get_password_from_bot()
                     # await self.client.sign_in(password=password)
                     logger.error("2FA password is required. Please disable it or implement get_password_from_bot.")
                     # You might want to stop the bot here or handle differently

                # Add handlers for other potential auth errors if necessary

            except Exception as e:
                logger.error(f"Error during auth handler: {e}")
            finally:
                self._auth_in_progress = False

        # Although start() doesn't directly use these args anymore,
        # telethon might internally trigger RpcError events that we now handle.
        # We might still need a way to *initiate* the phone number request.
        # The first sign_in call in client.start() should ideally trigger PhoneCodeEmptyError
        # if not already logged in.
        logger.info("Telethon authentication event handlers setup.")

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
            
            # Start the Telegram client
            # Telethon will now use the event handlers for auth prompts
            await self.client.start()
            logger.info("Telegram client started successfully")
            
            # Join channels
            self.channel_entities = await self.join_channels()
            if not self.channel_entities:
                logger.warning("No channels were successfully joined")
                # Depending on requirements, you might want to stop here
                # if channel joining is essential.
                # For now, letting it run to potentially process old messages.

            # Setup message handler for incoming messages in joined channels
            await self.setup_message_handler()
            
            self.is_running = True
            logger.info("Bot is now running and monitoring channels...")
            
            # Keep the telethon client running until disconnected
            await self.client.run_until_disconnected()
            
        except SessionPasswordNeededError:
            # This exception might still be raised if the event handler fails or 2FA is not handled
            logger.error("Two-factor authentication is enabled and not handled by UI bot. Please disable it or provide password handler.")
            return False
        except Exception as e:
            logger.error(f"Critical error in Telegram client startup: {e}")
            return False
        finally:
            self.is_running = False
            if self.client:
                await self.client.disconnect()
            logger.info("Telethon client stopped")
    
    async def stop(self):
        """Gracefully stop the bot"""
        if self.is_running and self.client:
            self.is_running = False
            await self.client.disconnect()
            logger.info("Bot stopped gracefully")

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
             await context.bot.send_message(chat_id=update.effective_chat.id, text="Bot configuration error: CHAT_ID not set.")
        return

    # Only process messages from the designated chat ID
    if str(update.effective_chat.id) == chat_id:
        user_response = update.message.text
        response_event.set()
        logger.info(f"Received UI bot message from {chat_id}: {user_response}")
        # Optionally send a confirmation back to the user
        # await context.bot.send_message(chat_id=chat_id, text="Received your input.")

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
        return

    render_external_url = os.getenv('RENDER_EXTERNAL_URL')
    port = int(os.getenv('PORT', 8080)) # Default to 8080 if PORT not set

    if not render_external_url:
        logger.error("RENDER_EXTERNAL_URL not found in environment variables. Cannot set up webhook.")
        # Fallback to polling for local development if URL is missing (optional)
        # In a production environment like Render, this should ideally not happen.
        try:
            logger.info("RENDER_EXTERNAL_URL not set, falling back to polling (for local development).")
            updater = Updater(bot_token)
            dispatcher = updater.dispatcher
            dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_ui_bot_message))
            logger.info("Starting UI bot polling...")
            updater.start_polling()
            updater.idle()
            logger.info("UI bot polling stopped.")
        except Exception as e:
             logger.error(f"Error during fallback polling: {e}")
        return

    try:
        updater = Updater(bot_token)
        dispatcher = updater.dispatcher

        # Add handler for all text messages from the specified chat ID
        dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_ui_bot_message))

        # Set the webhook
        webhook_url = render_external_url + '/webhook' # Assuming /webhook endpoint
        logger.info(f"Setting webhook to: {webhook_url} on port {port}")

        # Remove any existing webhook first (important for Render restarts)
        await updater.bot.delete_webhook()
        asyncio.sleep(1) # Give a moment for the delete to process

        updater.start_webhook(
            listen="0.0.0.0",
            port=port,
            url_path='webhook',
            webhook_url=webhook_url
        )

        logger.info("UI bot webhook started.")
        # Keep the updater running
        updater.idle()
        logger.info("UI bot webhook stopped.")

    except Exception as e:
        logger.error(f"Error running UI bot with webhook: {e}")

async def main():
    """Main entry point"""
    # Load environment variables here as well to ensure they are available for both bots
    load_dotenv()

    # Get the event loop
    loop = asyncio.get_event_loop()

    # Create tasks for both bots
    # Run the Telethon bot in a task
    telethon_bot = TelegramUIBot()
    telethon_bot_task = loop.create_task(telethon_bot.start())

    # Run the UI bot webhook in a task
    ui_bot_task = loop.create_task(run_ui_bot())

    # Wait for both tasks to complete (they are expected to run indefinitely)
    try:
        await asyncio.gather(telethon_bot_task, ui_bot_task)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping bots...")
        # Cancel tasks gracefully
        telethon_bot_task.cancel()
        ui_bot_task.cancel()
        try:
            await asyncio.gather(telethon_bot_task, ui_bot_task, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")

    except Exception as e:
        logger.error(f"Unexpected error in main gathering tasks: {e}")

    finally:
        # Ensure Telethon client disconnects on exit
        if telethon_bot.client and telethon_bot.client.is_connected():
             await telethon_bot.client.disconnect()
             logger.info("Telethon client disconnected during final cleanup.")


if __name__ == '__main__':
    try:
        # Get the current event loop or create a new one if none exists
        loop = asyncio.get_event_loop()
        if loop.is_running():
             logger.warning("Event loop is already running.")
             # If running in an environment like Jupyter, use run_until_complete
             # loop.run_until_complete(main())
        else:
             # Otherwise, run the main coroutine
             loop.run_until_complete(main())

    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error in __main__: {e}")
