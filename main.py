import os
import asyncio
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.channels import JoinChannelRequest

from config_validator import ConfigValidator
from session_handler import SessionHandler
from message_processor import MessageProcessor
from logger_config import setup_logger

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
            await self.client.start()
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

async def main():
    """Main entry point"""
    bot = TelegramUIBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping bot...")
        await bot.stop()
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        await bot.stop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
