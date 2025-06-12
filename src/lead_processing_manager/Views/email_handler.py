import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
import re
from lead_processing_manager.Configs.config import config
from lead_processing_manager.Models.models import Lead, Conversation, CommunicationChannel, SessionLocal
from lead_processing_manager.Views.base_handler import BaseCommunicationHandler
from lead_processing_manager.Utils.logging_utils import setup_logger
from lead_processing_manager.Utils.db_utils import db_session


class EmailHandler(BaseCommunicationHandler):
    def __init__(self):
        super().__init__()
        self.logger = setup_logger(__name__)
        self.smtp_server = config.EMAIL_SMTP_SERVER
        self.smtp_port = config.EMAIL_SMTP_PORT
        self.imap_server = config.EMAIL_IMAP_SERVER
        self.email_address = config.EMAIL_ADDRESS
        self.email_password = config.EMAIL_PASSWORD
        self.channel = CommunicationChannel.EMAIL
    
    def send_message(self, recipient: str, message: str, subject: str = None, 
                     is_html: bool = False) -> bool:
        """Send email message"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = recipient
            msg['Subject'] = subject or "Re: Lead Generation"
            
            msg.attach(MIMEText(message, 'html' if is_html else 'plain'))
            
            # Check if we're in test mode
            if hasattr(config, 'EMAIL_TEST_MODE') and config.EMAIL_TEST_MODE:
                test_message = f"\n📧 TEST MODE: Email Message\n" \
                             f"From: {self.email_address}\n" \
                             f"To: {recipient}\n" \
                             f"Subject: {msg['Subject']}\n" \
                             f"Message: {message}\n" \
                             f"Status: Would be sent in production mode\n"
                print(test_message)  # Print to console
                self.logger.info(test_message)  # Log to file
                return True
            
            # Real email sending
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_address, self.email_password)
                server.send_message(msg)
            
            return True
        except Exception as e:
            print(f"Error sending email: {e}")
            return False
    
    def check_messages(self) -> List[Dict]:
        """Check for new email messages"""
        messages = []
        try:
            with imaplib.IMAP4_SSL(self.imap_server) as imap:
                imap.login(self.email_address, self.email_password)
                imap.select('INBOX')
                
                _, message_numbers = imap.search(None, 'UNSEEN')
                
                for num in message_numbers[0].split():
                    _, msg_data = imap.fetch(num, '(RFC822)')
                    email_body = msg_data[0][1]
                    email_message = email.message_from_bytes(email_body)
                    
                    messages.append({
                        'from': email_message['from'],
                        'subject': email_message['subject'],
                        'body': self._get_email_body(email_message),
                        'date': email_message['date']
                    })
            
            return messages
        except Exception as e:
            print(f"Error checking emails: {e}")
            return []
    
    def _get_email_body(self, email_message) -> str:
        """Extract body from email message"""
        body = ""
        
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                elif part.get_content_type() == "text/html" and not body:
                    html_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    body = re.sub('<[^<]+?>', '', html_body)
        else:
            body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
        
        return body.strip()
    
    def _validate_lead_contact(self, lead: Lead) -> bool:
        """Validate lead has email address"""
        return bool(lead.email and lead.email_verified)
    
    def _get_lead_contact(self, lead: Lead) -> str:
        """Get lead's email address"""
        return lead.email
    
    def send_lead_email(self, lead: Lead, message: str) -> bool:
        """Send email to a lead and record in database"""
        subject = f"Helping {lead.company_name} Generate More Qualified Leads"
        
        if self.send_message(lead.email, message, subject):
            # Record in database
            with db_session() as db:
                conversation = Conversation(
                    lead_id=lead.id,
                    channel=self.channel,
                    direction="outbound",
                    message_content=message
                )
                db.add(conversation)
                return True
        return False
