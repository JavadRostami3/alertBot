import os
import logging
from typing import Dict, Any, Optional, Tuple
from telethon import TelegramClient
from telethon.network import connection

logger = logging.getLogger(__name__)

class SessionHandler:
    """Handles Telegram session creation and proxy configuration"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.session_name = 'telegram_ui_bot_session'
    
    async def create_client(self) -> TelegramClient:
        """Create and configure Telegram client with proxy if needed"""
        proxy_config = self._get_proxy_config()
        
        if proxy_config:
            logger.info(f"Creating client with {proxy_config[0]} proxy: {proxy_config[1]}:{proxy_config[2]}")
            client = TelegramClient(
                self.session_name,
                self.config['api_id'],
                self.config['api_hash'],
                proxy=proxy_config
            )
        else:
            logger.info("Creating client without proxy")
            client = TelegramClient(
                self.session_name,
                self.config['api_id'],
                self.config['api_hash']
            )
        
        return client
    
    def _get_proxy_config(self) -> Optional[Tuple]:
        """Get proxy configuration tuple for Telethon"""
        proxy_type = self.config.get('proxy_type')
        proxy_server = self.config.get('proxy_server')
        proxy_port = self.config.get('proxy_port')
        
        if not all([proxy_type, proxy_server, proxy_port]):
            return None
        
        proxy_type = proxy_type.lower()
        
        try:
            if proxy_type == 'socks5':
                # SOCKS5 proxy: (socks.SOCKS5, server, port, rdns, username, password)
                return ('socks5', proxy_server, proxy_port, True, None, None)
            
            elif proxy_type == 'http':
                # HTTP proxy: (socks.HTTP, server, port, rdns, username, password)
                return ('http', proxy_server, proxy_port, True, None, None)
            
            elif proxy_type == 'mtproto':
                # MTProto proxy
                proxy_secret = self.config.get('proxy_secret')
                if not proxy_secret:
                    logger.error("MTProto proxy requires proxy_secret")
                    return None
                
                # Convert hex secret to bytes
                try:
                    secret_bytes = bytes.fromhex(proxy_secret)
                except ValueError:
                    logger.error("Invalid proxy_secret format. Must be hex string.")
                    return None
                
                return (proxy_server, proxy_port, secret_bytes)
            
            else:
                logger.warning(f"Unsupported proxy type: {proxy_type}")
                return None
                
        except Exception as e:
            logger.error(f"Error configuring proxy: {e}")
            return None
    
    def cleanup_session(self):
        """Clean up session files if needed"""
        session_file = f"{self.session_name}.session"
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                logger.info("Session file cleaned up")
            except Exception as e:
                logger.warning(f"Could not remove session file: {e}")
