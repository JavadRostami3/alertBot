import logging
import sys
from datetime import datetime

def setup_logger(name: str = 'telegram_ui_bot', level: str = 'INFO') -> logging.Logger:
    """Setup and configure logger for the application"""
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # Create file handler
    file_handler = logging.FileHandler('telegram_bot.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Set formatter for handlers
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    # Log startup message
    logger.info("="*50)
    logger.info("Telegram UI Bot Logger Initialized")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*50)
    
    return logger

def set_telethon_log_level(level: str = 'WARNING'):
    """Set Telethon library log level to reduce noise"""
    telethon_logger = logging.getLogger('telethon')
    telethon_logger.setLevel(getattr(logging, level.upper()))
