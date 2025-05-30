import os
import asyncio
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.channels import JoinChannelRequest
from telegram.ext import Updater, MessageHandler, Filters

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
            
            # Initialize message processor
            self.message_processor = MessageProcessor(self.config)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False
    
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
            # Pass our custom functions to handle phone number and code requests
            # Note: This will pause and wait for input via the UI bot.
            await self.client.start(phone=get_phone_number_from_bot, code=get_code_from_bot)
            logger.info("Telegram client started successfully")
            
            # Join channels
            self.channel_entities = await self.join_channels()
            if not self.channel_entities:
                logger.warning("No channels were successfully joined")
                return False
            
            # Setup message handler
            await self.setup_message_handler()
            
            self.is_running = True
            logger.info("Bot is now running and monitoring channels...")
            
            # Keep the bot running
            await self.client.run_until_disconnected()
            
        except SessionPasswordNeededError:
            logger.error("Two-factor authentication is enabled. Please disable it or provide password.")
            return False
        except Exception as e:
            logger.error(f"Critical error in bot startup: {e}")
            return False
        finally:
            self.is_running = False
            if self.client:
                await self.client.disconnect()
            logger.info("Bot stopped")
    
    async def stop(self):
        """Gracefully stop the bot"""
        if self.is_running and self.client:
            self.is_running = False
            await self.client.disconnect()
            logger.info("Bot stopped gracefully")

# --- UI Bot Handler --- #
async def handle_ui_bot_message(update, context):
    """Handler for messages received by the UI bot."""
    global user_response
    global response_event

    chat_id = os.getenv('CHAT_ID')
    if not chat_id:
        logger.error("CHAT_ID not found in environment variables for UI bot handler.")
        return

    # Only process messages from the designated chat ID
    if str(update.effective_chat.id) == chat_id:
        user_response = update.message.text
        response_event.set()
        logger.info(f"Received UI bot message from {chat_id}: {user_response}")
    else:
        logger.warning(f"Received UI bot message from unexpected chat ID: {update.effective_chat.id}")
        # Optionally send a message back to the unexpected chat
        # await context.bot.send_message(chat_id=update.effective_chat.id, text="Unauthorized access.")

async def run_ui_bot():
    """Runs the Telegram UI bot to receive user input."""
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("BOT_TOKEN not found in environment variables. Cannot run UI bot.")
        return

    try:
        # Use webhook or polling based on deployment environment
        # For Render, webhook is usually preferred.
        # For local testing, polling is easier.
        # This example uses polling for simplicity.
        # TODO: Implement webhook for production deployment on Render.

        updater = Updater(bot_token)
        dispatcher = updater.dispatcher

        # Add handler for all text messages from the specified chat ID
        dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_ui_bot_message))

        # Start the Bot
        logger.info("Starting UI bot polling...")
        updater.start_polling()
        updater.idle()
        logger.info("UI bot polling stopped.")

    except Exception as e:
        logger.error(f"Error running UI bot: {e}")

async def main():
    """Main entry point"""
    # Load environment variables here as well to ensure they are available for both bots
    load_dotenv()

    # Create tasks for both bots
    telethon_bot_task = asyncio.create_task(TelegramUIBot().start())
    ui_bot_task = asyncio.create_task(run_ui_bot())

    # Run both tasks concurrently
    await asyncio.gather(telethon_bot_task, ui_bot_task)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
