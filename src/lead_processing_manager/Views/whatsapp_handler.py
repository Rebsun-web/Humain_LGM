# Whatsapp_Handler.py
import hmac
import hashlib
import requests
from typing import List, Dict, Tuple
from datetime import datetime
from flask import Flask, request, jsonify
from queue import Queue
from lead_processing_manager.Configs.config import config
from lead_processing_manager.Models.models import Lead, Conversation, CommunicationChannel, SessionLocal
from lead_processing_manager.Utils.rate_limiter import WhatsAppRateLimiter
from lead_processing_manager.Views.base_handler import BaseCommunicationHandler
from lead_processing_manager.Utils.logging_utils import setup_logger
from lead_processing_manager.Utils.db_utils import db_session


class WhatsAppMessage:
    def __init__(self, from_number: str, message_body: str, timestamp: datetime, message_id: str):
        self.from_number = from_number
        self.message_body = message_body
        self.timestamp = timestamp
        self.message_id = message_id


class WhatsAppHandler(BaseCommunicationHandler):
    def __init__(self):
        super().__init__()
        self.logger = setup_logger(__name__)
        self.test_mode = config.WHATSAPP_TEST_MODE
        self.rate_limiter = WhatsAppRateLimiter()
        self.channel = CommunicationChannel.WHATSAPP
        self.api_url = config.WHATSAPP_API_URL
        self.api_token = config.WHATSAPP_API_TOKEN
        self.phone_number_id = config.WHATSAPP_PHONE_NUMBER_ID
        self.webhook_verify_token = config.WHATSAPP_WEBHOOK_VERIFY_TOKEN
        self.app_secret = config.WHATSAPP_APP_SECRET
        
        # Queue for storing incoming messages
        self.message_queue = Queue()

        self.logger.info("WhatsAppHandler initialized")

        print(f"DEBUG: Access token starts with: {self.api_token[:20]}...")
        print(f"DEBUG: Access token ends with: ...{self.api_token[-10:]}")
    
    def send_message(self, recipient: str | int, message: str, **kwargs) -> bool:
        """Send WhatsApp message"""
        try:
            # Check rate limits
            can_send, reason = self.check_rate_limit()
            if not can_send:
                self.logger.warning(f"Rate limit reached: {reason}")
                return False
            
            # Always log the message
            test_message = f"\n🔔 WhatsApp Message\n" \
                           f"To: {recipient}\n" \
                           f"Message: {message}\n"
            self.logger.info(test_message)

            # Clean the phone number (remove spaces and dashes)
            recipient_str = str(recipient)
            clean_recipient = ''.join(filter(str.isdigit, recipient_str))
            if not clean_recipient.startswith('+'):
                clean_recipient = '+' + clean_recipient

            print(f"DEBUG: Clean recipient: {clean_recipient}")

            # Prepare the API request
            url = f"https://graph.facebook.com/v22.0/{self.phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "messaging_product": "whatsapp",
                "to": clean_recipient,
                "type": "text",
                "text": {"body": message.strip('"\'')}
            }

            # Make the API call
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                self.logger.info(f"WhatsApp message sent successfully to {clean_recipient}")
                return True
            else:
                self.logger.error(
                    f"Failed to send WhatsApp message. Status: {response.status_code}, "
                    f"Response: {response.text}"
                )
                return False
                
        except Exception as e:
            self.logger.error(f"Error sending WhatsApp: {str(e)}", exc_info=True)
            return False
    
    def check_messages(self) -> List[Dict]:
        """Check for new WhatsApp messages"""
        try:
            # TODO: Implement actual WhatsApp message checking
            # This is a placeholder for the actual implementation
            self.logger.debug("Checking for new WhatsApp messages")
            return []
            
        except Exception as e:
            self.logger.error(
                f"Error checking WhatsApp messages: {str(e)}",
                exc_info=True
            )
            return []
    
    def check_rate_limit(self) -> Tuple[bool, str]:
        """Check if we can send a message"""
        try:
            if self.rate_limiter:
                self.logger.debug("Checking rate limits")
                return self.rate_limiter.can_send_message()
            self.logger.debug("No rate limiter configured")
            return True, "No rate limit"
        except Exception as e:
            self.logger.error(
                f"Error checking rate limit: {str(e)}",
                exc_info=True
            )
            return False, f"Rate limit error: {str(e)}"
    
    def get_usage_stats(self) -> Dict:
        """Get current usage statistics"""
        try:
            if self.rate_limiter:
                self.logger.debug("Getting rate limiter stats")
                return self.rate_limiter.get_usage_stats()
            
            self.logger.debug("Using default usage stats (no rate limiter)")
            return {
                'daily_count': 0,
                'daily_limit': 1000,
                'daily_remaining': 1000,
                'hourly_count': 0,
                'hourly_limit': 100,
                'hourly_remaining': 100,
                'can_send': True
            }
        except Exception as e:
            self.logger.error(
                f"Error getting usage stats: {str(e)}",
                exc_info=True
            )
            return {
                'error': str(e),
                'can_send': False
            }
    
    def _validate_lead_contact(self, lead: Lead) -> bool:
        """Validate lead has phone number"""
        has_phone = bool(lead.phone_number)
        self.logger.debug(
            f"Validating phone for {lead.first_name}: {'✓' if has_phone else '✗'}"
        )
        return has_phone
    
    def _get_lead_contact(self, lead: Lead) -> str:
        """Get lead's phone number"""
        return lead.phone_number

    def send_lead_whatsapp(self, lead: Lead, message: str) -> bool:
        """Send WhatsApp to a lead and record in database"""
        if not lead.phone_number:
            self.logger.warning(f"No phone number for lead {lead.id}")
            return False
        
        success, reason = self.send_message(lead.phone_number, message)
        
        if success:
            # Record in database
            with db_session() as db:
                try:
                    conversation = Conversation(
                        lead_id=lead.id,
                        channel=CommunicationChannel.WHATSAPP,
                        direction="outbound",
                        message_content=message
                    )
                    db.add(conversation)
                    return True
                except Exception as e:
                    self.logger.error(f"Error recording WhatsApp message: {e}")
                    print(f"Error recording WhatsApp message: {e}")
                    return False
        else:
            print(f"Failed to send WhatsApp to {lead.first_name} {lead.last_name}: {reason}")
            return False
