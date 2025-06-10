import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
import re
from config import config
from models import Lead, Conversation, CommunicationChannel, SessionLocal


class EmailHandler:
    def __init__(self):
        self.smtp_server = config.EMAIL_SMTP_SERVER
        self.smtp_port = config.EMAIL_SMTP_PORT
        self.imap_server = config.EMAIL_IMAP_SERVER
        self.email_address = config.EMAIL_ADDRESS
        self.email_password = config.EMAIL_PASSWORD
    
    def send_email(self, to_email: str, subject: str, body: str, is_html: bool = False) -> bool:
        """Send email to a lead"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'html' if is_html else 'plain'))
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_address, self.email_password)
                server.send_message(msg)
            
            return True
        except Exception as e:
            print(f"Error sending email: {e}")
            return False
    
    def check_inbox(self) -> List[Dict]:
        """Check inbox for new emails from leads"""
        new_messages = []
        
        try:
            with imaplib.IMAP4_SSL(self.imap_server) as mail:
                mail.login(self.email_address, self.email_password)
                mail.select('inbox')
                
                # Search for unread emails
                _, message_ids = mail.search(None, 'UNSEEN')
                
                for msg_id in message_ids[0].split():
                    _, msg_data = mail.fetch(msg_id, '(RFC822)')
                    email_body = msg_data[0][1]
                    email_message = email.message_from_bytes(email_body)
                    
                    # Extract email details
                    from_email = self._extract_email_address(email_message['From'])
                    subject = email_message['Subject']
                    body = self._get_email_body(email_message)
                    date = email_message['Date']
                    
                    new_messages.append({
                        'from': from_email,
                        'subject': subject,
                        'body': body,
                        'date': date,
                        'message_id': msg_id
                    })
                    
                    # Mark as read
                    mail.store(msg_id, '+FLAGS', '\\Seen')
        
        except Exception as e:
            print(f"Error checking inbox: {e}")
        
        return new_messages
    
    def _extract_email_address(self, from_field: str) -> str:
        """Extract email address from From field"""
        match = re.search(r'[\w\.-]+@[\w\.-]+', from_field)
        return match.group(0) if match else from_field
    
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
                    # Simple HTML to text conversion
                    body = re.sub('<[^<]+?>', '', html_body)
        else:
            body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
        
        return body.strip()
    
    def send_lead_email(self, lead: Lead, message: str) -> bool:
        """Send email to a lead and record in database"""
        subject = f"Helping {lead.company_name} Generate More Qualified Leads"
        
        if self.send_email(lead.email, subject, message):
            # Record in database
            db = SessionLocal()
            conversation = Conversation(
                lead_id=lead.id,
                channel=CommunicationChannel.EMAIL,
                direction="outbound",
                message_content=message
            )
            db.add(conversation)
            db.commit()
            db.close()
            return True
        return False
