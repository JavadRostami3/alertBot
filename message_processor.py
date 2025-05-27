import os
import re
import asyncio
import logging
from typing import Optional, List
import google.generativeai as genai
from telethon import TelegramClient
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError

logger = logging.getLogger(__name__)

class MessageProcessor:
    """Processes incoming messages and handles AI response generation"""
    
    # UI/UX related keywords in Persian and English
    UI_KEYWORDS = [
        'UI', 'UX', 'interface', 'figma', 'sketch', 'adobe xd',
        'فرانت', 'طراحی رابط', 'رابط کاربری', 'تجربه کاربری',
        'ui designer', 'ux designer', 'فیگما', 'طراح رابط',
        'front-end', 'frontend', 'وب دیزاین', 'web design',
        'mobile design', 'app design', 'طراحی اپلیکیشن',
        'wireframe', 'prototype', 'mockup', 'طراحی موکاپ'
    ]
    
    def __init__(self, config):
        self.config = config
        self.processed_messages = set()  # To avoid duplicate processing
        self.rate_limit_delay = 30  # Seconds between messages to same user
        self.last_message_time = {}
        
        # Configure Gemini AI
        if self.config.get('gemini_api_key'):
            try:
                genai.configure(api_key=self.config['gemini_api_key'])
                self.model = genai.GenerativeModel('gemini-pro')
            except Exception as e:
                logger.error(f"Failed to configure Gemini AI: {e}")
                self.model = None
        else:
            logger.warning("Gemini API key not provided")
            self.model = None
    
    def contains_ui_keywords(self, text: str) -> bool:
        """Check if text contains UI/UX related keywords"""
        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in self.UI_KEYWORDS)
    
    def extract_username(self, text: str) -> Optional[str]:
        """Extract username from text"""
        # Look for @username pattern
        match = re.search(r'@([a-zA-Z0-9_]+)', text)
        if match:
            return match.group(1)  # Return without @ symbol
        return None
    
    def extract_contact_info(self, text: str) -> dict:
        """Extract various contact information from text"""
        contact_info = {}
        
        # Extract username
        username = self.extract_username(text)
        if username:
            contact_info['username'] = username
        
        # Extract phone numbers (Iranian format)
        phone_match = re.search(r'(\+98|0)?9\d{9}', text)
        if phone_match:
            contact_info['phone'] = phone_match.group(0)
        
        # Extract email addresses
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        if email_match:
            contact_info['email'] = email_match.group(0)
        
        return contact_info
    
    async def generate_custom_message(self, job_text: str) -> str:
        """Generate personalized response using Gemini AI"""
        if not self.model:
            return self._get_fallback_message()
        
        prompt = f"""
با توجه به آگهی استخدام زیر، یک پیام حرفه‌ای و دوستانه به زبان فارسی برای ارسال به کارفرما بنویس. پیام باید:

1. مودبانه و حرفه‌ای باشد
2. اشتیاق و علاقه به همکاری را نشان دهد
3. به طور خلاصه به تجربه مرتبط در زمینه طراحی UI/UX اشاره کند
4. حداکثر 3-4 خط باشد
5. با یک ایموجی مناسب شروع شود
6. به درخواست ارسال نمونه کار یا رزومه اشاره کند

متن آگهی:
{job_text}

پیام شخصی‌سازی شده:
"""
        
        try:
            response = await self.model.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Error generating AI response: {e}")
            return self._get_fallback_message()
    
    def _get_fallback_message(self) -> str:
        """Return fallback message when AI is not available"""
        return """🎨 سلام و وقت بخیر

با توجه به آگهی شما در زمینه طراحی UI/UX، تمایل دارم در این پروژه همکاری کنم. 
چندین سال تجربه در طراحی رابط کاربری و تجربه کاربری دارم.

در ادامه نمونه کارها و رزومه خود را ارسال می‌کنم.

با تشکر 🙏"""
    
    async def send_response_to_user(self, client: TelegramClient, username: str, message: str) -> bool:
        """Send personalized response and resume to user"""
        try:
            # Check rate limiting
            current_time = asyncio.get_event_loop().time()
            last_time = self.last_message_time.get(username, 0)
            
            if current_time - last_time < self.rate_limit_delay:
                logger.info(f"Rate limiting: skipping message to {username}")
                return False
            
            # Get user entity
            try:
                entity = await client.get_entity(username)
            except ValueError:
                logger.warning(f"User not found: {username}")
                return False
            except UserPrivacyRestrictedError:
                logger.warning(f"User privacy restricted: {username}")
                return False
            
            # Send text message
            await client.send_message(entity, message)
            logger.info(f"Message sent to {username}")
            
            # Send resume file if available
            await self._send_resume_file(client, entity, username)
            
            # Update rate limiting tracker
            self.last_message_time[username] = current_time
            return True
            
        except FloodWaitError as e:
            logger.warning(f"Flood wait error: {e.seconds} seconds")
            raise  # Re-raise to be handled by caller
        except Exception as e:
            logger.error(f"Error sending message to {username}: {e}")
            return False
    
    async def _send_resume_file(self, client: TelegramClient, entity, username: str):
        """Send resume file to user"""
        resume_filename = self.config.get('resume_filename', 'javad-rostami resume.pdf')
        
        # Try multiple possible paths for the resume file
        possible_paths = [
            os.path.join('resume', resume_filename),
            resume_filename,
            os.path.join(os.path.dirname(__file__), 'resume', resume_filename),
            os.path.join(os.path.dirname(__file__), resume_filename)
        ]
        
        resume_path = None
        for path in possible_paths:
            if os.path.exists(path):
                resume_path = path
                break
        
        portfolio_url = self.config.get('portfolio_url', '')
        
        if resume_path:
            try:
                caption = f"📄 رزومه و سوابق کاری\n🎨 نمونه کارها: {portfolio_url}"
                await client.send_file(entity, resume_path, caption=caption)
                logger.info(f"Resume file sent to {username}")
            except Exception as e:
                logger.error(f"Error sending resume file to {username}: {e}")
                # Send portfolio link as text if file sending fails
                if portfolio_url:
                    await client.send_message(entity, f"🎨 نمونه کارها: {portfolio_url}")
        else:
            logger.warning(f"Resume file not found at any of the expected paths")
            # Send portfolio link if resume file is not available
            if portfolio_url:
                await client.send_message(entity, f"🎨 نمونه کارها: {portfolio_url}")
    
    async def process_message(self, event, client: TelegramClient):
        """Process incoming message and send response if relevant"""
        try:
            message_text = event.message.message
            message_id = event.message.id
            
            # Skip if already processed
            if message_id in self.processed_messages:
                return
            
            # Skip empty messages
            if not message_text or len(message_text.strip()) < 10:
                return
            
            logger.debug(f"Processing message: {message_text[:100]}...")
            
            # Check if message contains UI/UX keywords
            if not self.contains_ui_keywords(message_text):
                return
            
            logger.info("UI/UX job posting detected")
            
            # Extract contact information
            contact_info = self.extract_contact_info(message_text)
            username = contact_info.get('username')
            
            if not username:
                logger.info("No username found in message")
                return
            
            logger.info(f"Found username: {username}")
            
            # Generate personalized response
            custom_message = await self.generate_custom_message(message_text)
            
            # Send response
            success = await self.send_response_to_user(client, username, custom_message)
            
            if success:
                logger.info(f"Successfully processed and responded to job posting from {username}")
                # Mark as processed
                self.processed_messages.add(message_id)
                
                # Clean up old processed messages to prevent memory issues
                if len(self.processed_messages) > 1000:
                    # Keep only the last 500 messages
                    self.processed_messages = set(list(self.processed_messages)[-500:])
            
        except Exception as e:
            logger.error(f"Error in process_message: {e}")
