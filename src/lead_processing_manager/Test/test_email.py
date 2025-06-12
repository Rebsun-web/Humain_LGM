import imaplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from lead_processing_manager.Configs.config import config

def test_email_connection():
    print("\n🔍 Testing Email Configuration...")
    print(f"Email Address: {config.EMAIL_ADDRESS}")
    print(f"SMTP Server: {config.EMAIL_SMTP_SERVER}")
    print(f"IMAP Server: {config.EMAIL_IMAP_SERVER}")
    
    # Test SMTP (sending emails)
    print("\nTesting SMTP connection...")
    try:
        with smtplib.SMTP(config.EMAIL_SMTP_SERVER, config.EMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)
            print("✅ SMTP Authentication successful!")
    except Exception as e:
        print(f"❌ SMTP Error: {str(e)}")
    
    # Test IMAP (receiving emails)
    print("\nTesting IMAP connection...")
    try:
        with imaplib.IMAP4_SSL(config.EMAIL_IMAP_SERVER) as imap:
            imap.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)
            print("✅ IMAP Authentication successful!")
            
            # List available mailboxes
            print("\nAvailable mailboxes:")
            status, mailboxes = imap.list()
            if status == 'OK':
                for mailbox in mailboxes:
                    print(f"  - {mailbox.decode()}")
    except Exception as e:
        print(f"❌ IMAP Error: {str(e)}")

if __name__ == "__main__":
    test_email_connection() 