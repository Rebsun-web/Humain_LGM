import requests
from typing import List
from datetime import datetime
from flask import Flask, request, jsonify
from threading import Thread
from queue import Queue
import hmac
import hashlib
from config import config
from models import Lead, Conversation, CommunicationChannel, SessionLocal

class WhatsAppMessage:
    def __init__(self, from_number: str, message_body: str, timestamp: datetime, message_id: str):
        self.from_number = from_number
        self.message_body = message_body
        self.timestamp = timestamp
        self.message_id = message_id

class WhatsAppHandler:
    def __init__(self):
        self.api_url = config.WHATSAPP_API_URL
        self.api_token = config.WHATSAPP_API_TOKEN
        self.phone_number_id = config.WHATSAPP_PHONE_NUMBER_ID
        self.webhook_verify_token = config.WHATSAPP_WEBHOOK_VERIFY_TOKEN
        self.app_secret = config.WHATSAPP_APP_SECRET
        
        # Queue for storing incoming messages
        self.message_queue = Queue()
        
        # Start webhook server
        self.start_webhook_server()
    
    def send_message(self, to_phone: str, message: str) -> bool:
        """Send WhatsApp message"""
        try:
            # Format phone number (remove spaces, dashes, etc.)
            to_phone = ''.join(filter(str.isdigit, to_phone))
            
            url = f"{self.api_url}/{self.phone_number_id}/messages"
            headers = {
                'Authorization': f'Bearer {self.api_token}',
                'Content-Type': 'application/json'
            }
            
            data = {
                'messaging_product': 'whatsapp',
                'to': to_phone,
                'type': 'text',
                'text': {'body': message}
            }
            
            response = requests.post(url, headers=headers, json=data)
            return response.status_code == 200
            
        except Exception as e:
            print(f"Error sending WhatsApp message: {e}")
            return False
    
    def check_messages(self) -> List[WhatsAppMessage]:
        """Check for new WhatsApp messages in the queue"""
        messages = []
        while not self.message_queue.empty():
            messages.append(self.message_queue.get())
        return messages
    
    def send_lead_whatsapp(self, lead: Lead, message: str) -> bool:
        """Send WhatsApp to a lead and record in database"""
        if lead.phone_number and self.send_message(lead.phone_number, message):
            # Record in database
            db = SessionLocal()
            try:
                conversation = Conversation(
                    lead_id=lead.id,
                    channel=CommunicationChannel.WHATSAPP,
                    direction="outbound",
                    message_content=message
                )
                db.add(conversation)
                db.commit()
                return True
            except Exception as e:
                print(f"Error recording WhatsApp message: {e}")
                db.rollback()
                return False
            finally:
                db.close()
        return False

    def verify_webhook_signature(self, request_data: bytes, signature_header: str) -> bool:
        """Verify that the webhook request came from WhatsApp"""
        try:
            # Get the SHA256 hash of the request body using your app secret
            expected_signature = hmac.new(
                self.app_secret.encode('utf-8'),
                request_data,
                hashlib.sha256
            ).hexdigest()
            
            # Compare with the signature from the header
            return hmac.compare_digest(signature_header, f"sha256={expected_signature}")
        except Exception as e:
            print(f"Error verifying webhook signature: {e}")
            return False

    def start_webhook_server(self):
        """Start the Flask server for receiving webhooks"""
        app = Flask(__name__)
        
        @app.route('/webhook/whatsapp', methods=['GET'])
        def verify_webhook():
            """Handle the webhook verification from WhatsApp"""
            mode = request.args.get('hub.mode')
            token = request.args.get('hub.verify_token')
            challenge = request.args.get('hub.challenge')
            
            if mode and token:
                if mode == 'subscribe' and token == self.webhook_verify_token:
                    return challenge
                return jsonify({'error': 'Invalid verification token'}), 403
            return jsonify({'error': 'Invalid request'}), 400

        @app.route('/webhook/whatsapp', methods=['POST'])
        def receive_message():
            """Handle incoming WhatsApp messages"""
            # Verify the request signature
            signature = request.headers.get('X-Hub-Signature-256')
            if not signature or not self.verify_webhook_signature(request.get_data(), signature):
                return jsonify({'error': 'Invalid signature'}), 403
            
            try:
                data = request.get_json()
                
                # Process incoming WhatsApp message
                messages_path = data.get('entry', [{}])[0]\
                    .get('changes', [{}])[0]\
                    .get('value', {}).get('messages', [])
                
                if messages_path:
                    for message in messages_path:
                        # Create WhatsAppMessage object
                        whatsapp_message = WhatsAppMessage(
                            from_number=message['from'],
                            message_body=message['text']['body'],
                            timestamp=datetime.fromtimestamp(
                                int(message['timestamp'])
                            ),
                            message_id=message['id']
                        )
                        
                        # Add to queue for processing
                        self.message_queue.put(whatsapp_message)
                
                return jsonify({'status': 'ok'})
                
            except Exception as e:
                print(f"Error processing webhook: {e}")
                return jsonify({'error': 'Internal server error'}), 500

        # Start the Flask server in a separate thread
        def run_server():
            app.run(host='0.0.0.0', port=config.WHATSAPP_WEBHOOK_PORT)
        
        Thread(target=run_server, daemon=True).start()
