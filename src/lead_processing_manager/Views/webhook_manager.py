# webhook_manager.py
import hmac
import hashlib
import asyncio
from threading import Thread
from flask import Flask, request, jsonify
from datetime import datetime
from lead_processing_manager.Configs.config import config
from lead_processing_manager.Main.lead_processor import LeadProcessor
from lead_processing_manager.Models.models import (
    CommunicationChannel, Lead, Meeting, LeadStatus
)
from lead_processing_manager.Utils.db_utils import db_session
from lead_processing_manager.Utils.logging_utils import setup_logger


class WebhookManager:
    def __init__(self, lead_processor: LeadProcessor):
        self.logger = setup_logger(__name__)
        self.lead_processor = lead_processor
        self.app = Flask(__name__)
        self.setup_routes()
        
    def setup_routes(self):
        """Set up all webhook routes"""
        
        # WhatsApp webhook routes
        @self.app.route('/webhook/whatsapp', methods=['GET'])
        def verify_whatsapp_webhook():
            """Handle WhatsApp webhook verification"""
            mode = request.args.get('hub.mode')
            token = request.args.get('hub.verify_token')
            challenge = request.args.get('hub.challenge')
            
            if mode and token:
                if mode == 'subscribe' and token == config.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
                    self.logger.info("WhatsApp webhook verified successfully")
                    return challenge
                return jsonify({'error': 'Invalid verification token'}), 403
            return jsonify({'error': 'Invalid request'}), 400
        
        @self.app.route('/webhook/whatsapp', methods=['POST'])
        def receive_whatsapp_message():
            """Handle incoming WhatsApp messages"""
            # # Verify signature
            # signature = request.headers.get('X-Hub-Signature-256')
            # if not signature or not self._verify_whatsapp_signature(request.get_data(), signature):
            #     return jsonify({'error': 'Invalid signature'}), 403
            
            try:
                # Handle different content types
                if request.is_json:
                    data = request.get_json()
                else:
                    # Parse as JSON even if Content-Type is wrong
                    try:
                        data = request.get_json(force=True)
                    except:
                        data = {}
                
                print(f"DEBUG: Received WhatsApp data: {data}")  # Add this
                self.logger.debug(f"Received WhatsApp webhook: {data}")
                
                # Process incoming messages
                entry = data.get('entry', [])
                print(f"DEBUG: Entry data: {entry}")

                for entry_item in entry:
                    changes = entry_item.get('changes', [])
                    for change in changes:
                        value = change.get('value', {})
                        messages = value.get('messages', [])
                        print(f"DEBUG: Found {len(messages)} messages")
                        
                        for message in messages:
                            self._process_whatsapp_message(message, value)
                            print(f"DEBUG: Processing message: {message}")
                
                return jsonify({'status': 'ok'})
                
            except Exception as e:
                self.logger.error(f"Error processing WhatsApp webhook: {e}")
                return jsonify({'error': 'Internal server error'}), 500

        # Email webhook routes (for email services like SendGrid, Mailgun)
        @self.app.route('/webhook/email', methods=['POST'])
        def receive_email_event():
            """Handle email service webhooks (bounces, opens, clicks, replies)"""
            try:
                data = request.get_json()
                self.logger.debug(f"Received email webhook: {data}")
                
                # Process different email events
                event_type = data.get('event_type') or data.get('eventType')
                
                if event_type in ['bounce', 'dropped']:
                    self._handle_email_bounce(data)
                elif event_type == 'open':
                    self._handle_email_open(data)
                elif event_type == 'click':
                    self._handle_email_click(data)
                elif event_type == 'reply':
                    self._handle_email_reply(data)
                
                return jsonify({'status': 'ok'})
                
            except Exception as e:
                self.logger.error(f"Error processing email webhook: {e}")
                return jsonify({'error': 'Internal server error'}), 500

        # Calendar webhook routes
        @self.app.route('/webhook/calendar', methods=['POST'])
        def receive_calendar_event():
            """Handle calendar webhooks (meeting confirmations, changes)"""
            try:
                data = request.get_json()
                self.logger.debug(f"Received calendar webhook: {data}")
                
                # Process calendar events
                event_type = data.get('type')
                if event_type == 'meeting_accepted':
                    self._handle_meeting_accepted(data)
                elif event_type == 'meeting_declined':
                    self._handle_meeting_declined(data)
                elif event_type == 'meeting_rescheduled':
                    self._handle_meeting_rescheduled(data)
                
                return jsonify({'status': 'ok'})
                
            except Exception as e:
                self.logger.error(f"Error processing calendar webhook: {e}")
                return jsonify({'error': 'Internal server error'}), 500

        # Health check endpoint
        @self.app.route('/webhook/health', methods=['GET'])
        def health_check():
            """Health check endpoint"""
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'services': {
                    'whatsapp': config.WHATSAPP_ENABLED,
                    'email': config.EMAIL_ENABLED,
                    'calendar': True
                }
            })

    def _verify_whatsapp_signature(self, request_data: bytes, signature_header: str) -> bool:
        """Verify WhatsApp webhook signature"""
        try:
            expected_signature = hmac.new(
                config.WHATSAPP_APP_SECRET.encode('utf-8'),
                request_data,
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature_header, f"sha256={expected_signature}")
        except Exception as e:
            self.logger.error(f"Error verifying WhatsApp signature: {e}")
            return False

    def _process_whatsapp_message(self, message: dict, value: dict):
        try:
            from_number = message.get('from')
            message_body = message.get('text', {}).get('body', '')

            print(f"DEBUG: Raw from_number: {from_number}")
            print(f"DEBUG: Message body: {message_body}")
            
            self.logger.info(f"Processing WhatsApp message from {from_number}: {message_body}")
            
            with db_session() as db:
                clean_number = ''.join(filter(str.isdigit, from_number))
                print(f"DEBUG: Cleaned number: {clean_number}")

                # Check how your lead's phone is stored
                lead = db.query(Lead).filter_by(phone_number="+31653470562").first()
                if lead:
                    print(f"DEBUG: Found lead by exact match: {lead.phone_number}")
                
                # Try the original search
                lead = db.query(Lead).filter(
                    Lead.phone_number.contains(clean_number)
                ).first()
                
                if lead:
                    print(f"DEBUG: Found lead: {lead.first_name} {lead.last_name}, phone: {lead.phone_number}")

                    lead_id = lead.id

                    def process_async():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        with db_session() as async_db:
                            fresh_lead = async_db.query(Lead).filter_by(id=lead_id).first()
                            if fresh_lead:
                                loop.run_until_complete(
                                    self.lead_processor.process_lead_response(
                                        fresh_lead, message_body, CommunicationChannel.WHATSAPP
                                    )
                                )
                        loop.close()
                    
                    Thread(target=process_async, daemon=True).start()
                else:
                    print(f"DEBUG: No lead found for cleaned number: {clean_number}")
                    self.logger.warning(f"No lead found for phone number: {from_number}")
                    
        except Exception as e:
            print(f"ERROR processing message: {e}")
            self.logger.error(f"Error processing WhatsApp message: {e}")

    def _handle_email_bounce(self, data: dict):
        """Handle email bounce events (fails to be sent)"""
        email = data.get('email')
        reason = data.get('reason', 'Unknown bounce reason')
        
        self.logger.warning(f"Email bounced for {email}: {reason}")
        
        # Update lead email status
        with db_session() as db:
            lead = db.query(Lead).filter_by(email=email).first()
            if lead:
                lead.email_verified = False
                lead.notes = f"{lead.notes or ''}\nEmail bounced: {reason}"
                db.add(lead)

    def _handle_email_open(self, data: dict):
        """Handle email open events"""
        email = data.get('email')
        self.logger.info(f"Email opened by {email}")

    def _handle_email_click(self, data: dict):
        """Handle email click events"""
        email = data.get('email')
        url = data.get('url')
        self.logger.info(f"Email link clicked by {email}: {url}")

    def _handle_email_reply(self, data: dict):
        """Handle email reply events"""
        try:
            email = data.get('from')
            subject = data.get('subject', '')
            body = data.get('text', '')
            
            self.logger.info(f"Email reply from {email}")
            
            # Find lead and process response
            with db_session() as db:
                lead = db.query(Lead).filter_by(email=email).first()
                if lead:
                    asyncio.create_task(
                        self.lead_processor.process_lead_response(
                            lead, body, CommunicationChannel.EMAIL
                        )
                    )
                    
        except Exception as e:
            self.logger.error(f"Error handling email reply: {e}")

    def _handle_meeting_accepted(self, data: dict):
        """Handle meeting acceptance"""
        event_id = data.get('event_id')
        attendee_email = data.get('attendee_email')
        
        self.logger.info(f"Meeting accepted by {attendee_email} for event {event_id}")
        
        # Update meeting status in database
        with db_session() as db:
            meeting = db.query(Meeting).filter_by(calendar_event_id=event_id).first()
            if meeting:
                meeting.status = 'confirmed'
                lead = db.query(Lead).filter_by(id=meeting.lead_id).first()
                if lead:
                    lead.status = LeadStatus.MEETING_SCHEDULED
                db.add(meeting)
                db.add(lead)

    def _handle_meeting_declined(self, data: dict):
        """Handle meeting decline"""
        event_id = data.get('event_id')
        attendee_email = data.get('attendee_email')
        
        self.logger.info(f"Meeting declined by {attendee_email} for event {event_id}")

        # Delete meeting from the database
        with db_session() as db:
            meeting = db.query(Meeting).filter_by(calendar_event_id=event_id).first()
            if meeting:
                meeting.status = 'cancelled'
                lead = db.query(Lead).filter_by(id=meeting.lead_id).first()
                if lead:
                    lead.status = LeadStatus.MEETING_CANCELED
                db.add(meeting)
                db.add(lead)

    def _handle_meeting_rescheduled(self, data: dict):
        """Handle meeting reschedule"""
        event_id = data.get('event_id')
        new_time_str = data.get('new_time')
        try:
            # Parse ISO format string to datetime
            new_time = datetime.fromisoformat(new_time_str)
        except Exception:
            self.logger.error(f"Invalid datetime format for new_time: {new_time_str}")
            return
        
        self.logger.info(f"Meeting rescheduled for event {event_id} to {new_time}")

        # Reschedule meeting from the database
        with db_session() as db:
            meeting = db.query(Meeting).filter_by(calendar_event_id=event_id).first()
            if meeting:
                meeting.scheduled_time = new_time
                lead = db.query(Lead).filter_by(id=meeting.lead_id).first()
                if lead:
                    lead.status = LeadStatus.MEETING_SCHEDULED
                db.add(meeting)
                db.add(lead)

    def run(self, port=5000):
        """Run the Flask app"""
        self.app.run(host="0.0.0.0", port=port)
