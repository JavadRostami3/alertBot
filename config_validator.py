import os
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class ConfigValidator:
    """Validates and loads configuration from environment variables"""
    
    REQUIRED_VARS = {
        'API_ID': int,
        'API_HASH': str,
        'GEMINI_API_KEY': str,
        'CHANNELS': str,
        'PORTFOLIO_URL': str
    }
    
    OPTIONAL_VARS = {
        'CV_URL': str,
        'PROXY_TYPE': str,
        'PROXY_SERVER': str,
        'PROXY_PORT': int,
        'PROXY_SECRET': str,
        'RESUME_FILENAME': str
    }
    
    def validate_config(self) -> Dict[str, Any]:
        """Validate and return configuration dictionary"""
        config = {}
        
        # Validate required variables
        for var_name, var_type in self.REQUIRED_VARS.items():
            value = os.getenv(var_name)
            if not value:
                raise ValueError(f"Required environment variable {var_name} is missing")
            
            try:
                if var_type == int:
                    config[var_name.lower()] = int(value)
                else:
                    config[var_name.lower()] = value
            except ValueError:
                raise ValueError(f"Invalid type for {var_name}: expected {var_type.__name__}")
        
        # Process channels
        channels = config['channels'].split(',')
        config['channels'] = [ch.strip() for ch in channels if ch.strip()]
        
        if not config['channels']:
            raise ValueError("No valid channels found in CHANNELS environment variable")
        
        # Validate optional variables
        for var_name, var_type in self.OPTIONAL_VARS.items():
            value = os.getenv(var_name)
            if value:
                try:
                    if var_type == int:
                        config[var_name.lower()] = int(value)
                    else:
                        config[var_name.lower()] = value
                except ValueError:
                    logger.warning(f"Invalid type for optional variable {var_name}: expected {var_type.__name__}")
            else:
                config[var_name.lower()] = None
        
        # Set default resume filename if not provided
        if not config.get('resume_filename'):
            config['resume_filename'] = 'javad-rostami resume.pdf'
        
        # Validate proxy configuration
        self._validate_proxy_config(config)
        
        # Validate URLs
        self._validate_urls(config)
        
        logger.info("Configuration validation completed successfully")
        return config
    
    def _validate_proxy_config(self, config: Dict[str, Any]) -> None:
        """Validate proxy configuration"""
        proxy_type = config.get('proxy_type')
        proxy_server = config.get('proxy_server')
        proxy_port = config.get('proxy_port')
        
        if proxy_type:
            if proxy_type.lower() not in ['socks5', 'http', 'mtproto']:
                logger.warning(f"Unsupported proxy type: {proxy_type}. Supported types: socks5, http, mtproto")
                config['proxy_type'] = None
            
            if proxy_type.lower() == 'mtproto':
                if not config.get('proxy_secret'):
                    logger.warning("MTProto proxy requires proxy_secret")
                    config['proxy_type'] = None
            
            if proxy_server and proxy_port:
                if proxy_port < 1 or proxy_port > 65535:
                    logger.warning(f"Invalid proxy port: {proxy_port}")
                    config['proxy_port'] = None
            else:
                if proxy_type:
                    logger.warning("Proxy type specified but server/port missing")
    
    def _validate_urls(self, config: Dict[str, Any]) -> None:
        """Validate URL format"""
        for url_key in ['portfolio_url', 'cv_url']:
            url = config.get(url_key)
            if url and not (url.startswith('http://') or url.startswith('https://')):
                logger.warning(f"Invalid URL format for {url_key}: {url}")
    
    def print_config_summary(self, config: Dict[str, Any]) -> None:
        """Print a summary of the loaded configuration"""
        logger.info("=== Configuration Summary ===")
        logger.info(f"API ID: {config['api_id']}")
        logger.info(f"Channels: {len(config['channels'])} channels configured")
        logger.info(f"Proxy: {'Enabled' if config.get('proxy_type') else 'Disabled'}")
        logger.info(f"Portfolio URL: {'Set' if config.get('portfolio_url') else 'Not set'}")
        logger.info(f"Resume file: {config.get('resume_filename', 'Not specified')}")
        logger.info("==============================")
