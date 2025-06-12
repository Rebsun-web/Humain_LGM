from abc import ABC, abstractmethod
from typing import Optional, Dict, List
from lead_processing_manager.Models.models import Lead, Conversation, CommunicationChannel
from lead_processing_manager.Utils.db_utils import db_session


class BaseCommunicationHandler(ABC):
    """Base class for all communication channel handlers"""
    
    def __init__(self):
        self.channel: Optional[CommunicationChannel] = None
    
    @abstractmethod
    def send_message(self, recipient: str, message: str, **kwargs) -> bool:
        """Send a message through the channel"""
        pass
    
    @abstractmethod
    def check_messages(self) -> List[Dict]:
        """Check for new messages"""
        pass
    
    def send_to_lead(self, lead: Lead, message: str) -> bool:
        """Send message to a lead and record in database"""
        if not self._validate_lead_contact(lead):
            return False
            
        success = self.send_message(self._get_lead_contact(lead), message)
        
        if success and self.channel:
            with db_session() as db:
                conversation = Conversation(
                    lead_id=lead.id,
                    channel=self.channel,
                    direction="outbound",
                    message_content=message
                )
                db.add(conversation)
        
        return success
    
    @abstractmethod
    def _validate_lead_contact(self, lead: Lead) -> bool:
        """Validate that lead has required contact information"""
        pass
    
    @abstractmethod
    def _get_lead_contact(self, lead: Lead) -> str:
        """Get lead's contact information for this channel"""
        pass
