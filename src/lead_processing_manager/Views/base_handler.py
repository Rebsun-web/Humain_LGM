# base_handler.py
from abc import ABC, abstractmethod
from typing import Dict
from lead_processing_manager.Models.models import Lead, Conversation
from lead_processing_manager.Utils.db_utils import db_session
from lead_processing_manager.Utils.logging_utils import setup_logger


class BaseCommunicationHandler(ABC):
    def __init__(self):
        self.logger = setup_logger(self.__class__.__name__)
    
    def send_to_lead(self, lead: Lead, message: str) -> bool:
        """Send message to lead and store in database"""
        try:
            # Validate lead contact
            if not self._validate_lead_contact(lead):
                self.logger.warning(f"Invalid contact info for lead {lead.id}")
                return False
            
            # Get contact info
            contact = self._get_lead_contact(lead)
            
            # Send the message
            success = self.send_message(contact, message)
            
            if success:
                # Store conversation with retry logic already built into db_session
                with db_session() as db:
                    conversation = Conversation(
                        lead_id=lead.id,
                        channel=self.channel,
                        direction="outbound",
                        message_content=message
                    )
                    db.add(conversation)
                    self.logger.info(f"Message sent and stored for lead {lead.id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error sending message to lead {lead.id}: {str(e)}", exc_info=True)
            return False