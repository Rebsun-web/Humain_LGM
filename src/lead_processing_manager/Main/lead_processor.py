from datetime import datetime, timedelta
from typing import Dict, List, Optional
from lead_processing_manager.Models.models import (
    Lead, LeadStatus, Conversation, Meeting, CommunicationChannel
)
from lead_processing_manager.Views.gpt_handler import GPTHandler
from lead_processing_manager.Views.email_handler import EmailHandler
from lead_processing_manager.Views.whatsapp_handler import WhatsAppHandler
from lead_processing_manager.Views.telegram_bot import TelegramBot
from lead_processing_manager.Views.calendar_handler import CalendarHandler
from lead_processing_manager.Views.templates import Templates
from lead_processing_manager.Utils.db_utils import db_session
from lead_processing_manager.Utils.logging_utils import setup_logger, log_function_call
from lead_processing_manager.Configs.config import config


class LeadProcessor:
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.gpt = GPTHandler()
        self.email_handler = EmailHandler()
        self.whatsapp_handler = WhatsAppHandler() if config.WHATSAPP_ENABLED else None
        self.telegram_bot = TelegramBot()
        self.calendar_handler = CalendarHandler()
        self.logger.info("LeadProcessor initialized successfully")

    @log_function_call(setup_logger(__name__))
    async def process_new_lead(self, lead: Lead):
        """Process a newly added lead with multi-channel outreach"""
        try:
            self.logger.info(f"Processing new lead: {lead.first_name} {lead.last_name}")
            
            # Generate outreach message
            outreach_message = self._generate_outreach_message(lead)
            
            # Track which channels were used
            channels_used = []
            send_success = False
            
            # Try Email first
            if self._can_use_email(lead):
                self.logger.debug(f"Attempting email outreach to {lead.email}")
                if self.email_handler.send_to_lead(lead, outreach_message):
                    channels_used.append("Email")
                    send_success = True
                    self.logger.info(f"Email sent successfully to {lead.email}")
            else:
                self.logger.debug(
                    f"Email not available for {lead.first_name} {lead.last_name}"
                )
            
            # Try WhatsApp if enabled
            if self._can_use_whatsapp(lead):
                self.logger.debug(
                    f"Attempting WhatsApp outreach to {lead.phone_number}"
                )
                if await self._try_whatsapp_outreach(lead, outreach_message):
                    channels_used.append("WhatsApp")
                    send_success = True
                    self.logger.info(
                        f"WhatsApp sent successfully to {lead.phone_number}"
                    )
                else:
                    self.logger.debug(
                        f"WhatsApp not available for {lead.first_name} {lead.last_name}"
                    )
            
            # Update lead status if any channel succeeded
            if send_success:
                # Update lead status
                self._update_lead_status(
                    lead, 
                    LeadStatus.CONTACTED,
                    next_follow_up_days=2
                )
                
                # Save changes in a new session
                with db_session() as db:
                    db.merge(lead)
                    db.commit()
                    self.logger.info(
                        f"Updated lead status to {LeadStatus.CONTACTED}"
                    )
                
                await self._notify_outreach_success(lead, channels_used)
            else:
                await self._notify_outreach_failure(lead)
                self.logger.warning(
                    f"No available channels for {lead.first_name} {lead.last_name}"
                )
                    
        except Exception as e:
            self.logger.error(
                f"Error processing lead {lead.id}: {str(e)}",
                exc_info=True
            )
            raise
    
    @log_function_call(setup_logger(__name__))
    def _generate_outreach_message(self, lead: Lead) -> str:
        """Generate personalized outreach message"""
        try:
            industry = self._guess_industry(lead.company_name)
            self.logger.debug(f"Detected industry for {lead.company_name}: {industry}")
            
            if config.USE_TEMPLATES:
                self.logger.debug("Using template for outreach message")
                return Templates.get_initial_outreach(
                    lead.first_name, industry, "Dubai"
                )
            else:
                self.logger.debug("Using GPT for outreach message")
                return self.gpt.generate_initial_outreach(lead)
        except Exception as e:
            self.logger.error(
                f"Error generating outreach message for {lead.id}: {str(e)}",
                exc_info=True
            )
            raise
    
    def _can_use_email(self, lead: Lead) -> bool:
        """Check if email can be used for this lead"""
        return bool(lead.email_verified and lead.email and config.EMAIL_ENABLED)
    
    def _can_use_whatsapp(self, lead: Lead) -> bool:
        """Check if WhatsApp can be used for this lead"""
        return bool(
            lead.phone_number and 
            config.WHATSAPP_ENABLED and 
            self.whatsapp_handler
        )
    
    async def _try_whatsapp_outreach(self, lead: Lead, message: str) -> bool:
        """Attempt to send WhatsApp message with rate limiting"""
        if not self.whatsapp_handler:
            return False
            
        # Check rate limits
        can_send, reason = self.whatsapp_handler.check_rate_limit()
        if not can_send:
            print(f"WhatsApp rate limit reached: {reason}")
            await self.telegram_bot.send_message(
                f"⚠️ Cannot send WhatsApp to {lead.first_name}: {reason}"
            )
            return False
        
        return self.whatsapp_handler.send_to_lead(lead, message)
    
    async def process_lead_response(self, lead: Lead, message: str, 
                                  channel: CommunicationChannel):
        """Process a response from a lead"""
        with db_session() as db:
            # Store inbound conversation
            self._store_conversation(db, lead, channel, "inbound", message)
            
            # Analyze intent and update status
            intent = self.gpt.analyze_message_intent(message)
            self._update_lead_status_from_intent(lead, intent)
            
            # Get conversation history and update summary
            conversations = self._get_lead_conversations(db, lead)
            lead.conversation_summary = self.gpt.summarize_conversation(conversations)
            
            # Generate and send reply
            reply = self.gpt.generate_reply(lead, conversations, message)
            handler = self._get_channel_handler(channel)
            if handler:
                handler.send_to_lead(lead, reply)
            
            # Update last contact
            lead.last_contact_date = datetime.utcnow()
            db.add(lead)
        
        # Handle notifications and meeting requests
        await self._handle_response_notifications(lead, message, intent)
    
    def _store_conversation(self, db, lead: Lead, channel: CommunicationChannel,
                          direction: str, message: str):
        """Store a conversation entry"""
        conversation = Conversation(
            lead_id=lead.id,
            channel=channel,
            direction=direction,
            message_content=message
        )
        db.add(conversation)
    
    def _update_lead_status_from_intent(self, lead: Lead, intent: Dict):
        """Update lead status based on message intent"""
        if intent['sentiment'] == 'negative':
            lead.status = LeadStatus.NOT_INTERESTED
        elif intent['requesting_meeting'] == 'yes':
            lead.status = LeadStatus.MEETING_REQUESTED
        elif intent['expressing_interest'] == 'yes':
            lead.status = LeadStatus.INTERESTED
        else:
            lead.status = LeadStatus.RESPONDED
    
    def _get_lead_conversations(self, db, lead: Lead) -> list:
        """Get all conversations for a lead"""
        return db.query(Conversation).filter_by(
            lead_id=lead.id
        ).order_by(Conversation.timestamp).all()
    
    async def _handle_response_notifications(self, lead: Lead, message: str, 
                                          intent: Dict):
        """Handle notifications after lead response"""
        await self.telegram_bot.notify_lead_responded(
            lead, message, intent['sentiment']
        )
        if intent['requesting_meeting'] == 'yes':
            await self.telegram_bot.request_meeting_times(lead, message)
    
    def _get_channel_handler(self, channel: CommunicationChannel):
        """Get the appropriate communication handler for a channel"""
        if channel == CommunicationChannel.EMAIL:
            return self.email_handler
        elif channel == CommunicationChannel.WHATSAPP:
            return self.whatsapp_handler
        return None
    
    async def process_follow_ups(self):
        """Process leads that need follow-up"""
        with db_session() as db:
            leads_to_follow_up = self._get_leads_for_followup(db)
            
            for lead in leads_to_follow_up:
                await self._process_single_followup(db, lead)
    
    def _get_leads_for_followup(self, db):
        """Get leads that need follow-up"""
        return db.query(Lead).filter(
            Lead.next_follow_up_date <= datetime.utcnow(),
            Lead.status.in_([LeadStatus.CONTACTED, LeadStatus.FOLLOW_UP])
        ).all()
    
    async def _process_single_followup(self, db, lead: Lead):
        """Process follow-up for a single lead"""
        conversations = self._get_lead_conversations(db, lead)
        follow_up = self.gpt.generate_reply(
            lead, 
            conversations, 
            "[SYSTEM: Generate a follow-up message as no response received]"
        )
        
        # Try preferred channel first, then fallback
        sent = await self._send_followup_message(lead, follow_up)
        
        if sent:
            self._update_lead_status(
                lead, 
                LeadStatus.FOLLOW_UP,
                next_follow_up_days=7
            )
            db.add(lead)
    
    async def _send_followup_message(self, lead: Lead, message: str) -> bool:
        """Send follow-up message through available channels"""
        if self._can_use_email(lead):
            if self.email_handler.send_to_lead(lead, message):
                return True
                
        if self._can_use_whatsapp(lead):
            if await self._try_whatsapp_outreach(lead, message):
                return True
                
        return False
    
    def _update_lead_status(self, lead: Lead, status: LeadStatus, 
                        next_follow_up_days: int = None):
        """Update lead status and follow-up date"""
        lead.status = status
        lead.last_contact_date = datetime.utcnow()
        if next_follow_up_days:
            lead.next_follow_up_date = (
                datetime.utcnow() + timedelta(days=next_follow_up_days)
            )
    
    async def process_bulk_whatsapp_outreach(self):
        """Process bulk WhatsApp outreach to leads"""
        if not (self.whatsapp_handler and config.WHATSAPP_ENABLED):
            self.logger.debug("WhatsApp outreach disabled or handler not available")
            return
        
        with db_session() as db:
            # Get leads that haven't been contacted yet
            leads = db.query(Lead).filter(
                Lead.status == LeadStatus.NEW,
                Lead.phone_number.isnot(None)  # Has phone number
            ).all()

            self.logger.info(f"Found {len(leads)} leads for WhatsApp outreach")

            for lead in leads:
                try:
                    # Generate outreach message
                    message = self._generate_outreach_message(lead)

                    # Try to send WhatsApp
                    if await self._try_whatsapp_outreach(lead, message):
                        self._update_lead_status(
                            lead,
                            LeadStatus.CONTACTED,
                            next_follow_up_days=2
                        )
                        db.add(lead)
                        await self._notify_outreach_success(lead, ["WhatsApp"])
                        self.logger.info(
                            f"WhatsApp outreach successful for {lead.first_name}"
                        )
                    else:
                        self.logger.warning(
                            f"WhatsApp outreach failed for {lead.first_name}"
                        )

                except Exception as e:
                    self.logger.error(
                        f"Error in WhatsApp outreach for lead {lead.id}: {str(e)}",
                        exc_info=True
                    )
                    continue
    
    async def schedule_meeting(self, lead_id: int, meeting_time: datetime, 
                            duration_minutes: int = 30):
        """Schedule a meeting with a lead"""
        with db_session() as db:
            lead = db.query(Lead).filter_by(id=lead_id).first()
            if not lead:
                return
            
            event_id = self._create_calendar_event(lead, meeting_time, duration_minutes)
            
            if event_id:
                self._store_meeting(db, lead, event_id, meeting_time, duration_minutes)
                await self._send_meeting_confirmation(lead, meeting_time)
    
    def _create_calendar_event(self, lead: Lead, meeting_time: datetime,
                            duration_minutes: int) -> str:
        """Create calendar event for meeting"""
        return self.calendar_handler.create_meeting(
            summary=f"Meeting with {lead.first_name} {lead.last_name} - "
                    f"{lead.company_name}",
            start_time=meeting_time,
            duration_minutes=duration_minutes,
            attendee_email=lead.email,
            description=f"Lead Generation Discussion\n\n"
                        f"Lead Summary:\n{lead.conversation_summary}"
        )
    
    def _store_meeting(self, db, lead: Lead, event_id: str, 
                    meeting_time: datetime, duration_minutes: int):
        """Store meeting details in database"""
        meeting = Meeting(
            lead_id=lead.id,
            scheduled_time=meeting_time,
            duration_minutes=duration_minutes,
            calendar_event_id=event_id,
            status='confirmed'
        )
        db.add(meeting)
        
        lead.status = LeadStatus.MEETING_SCHEDULED
        db.add(lead)
    
    async def _send_meeting_confirmation(self, lead: Lead, meeting_time: datetime):
        """Send meeting confirmation to lead"""
        confirmation = (
            f"Great! I've scheduled our meeting for "
            f"{meeting_time.strftime('%A, %B %d at %I:%M %p')}.\n\n"
            f"You should receive a calendar invitation shortly. "
            f"Looking forward to discussing how we can help "
            f"{lead.company_name} generate more qualified leads.\n\n"
            f"Best regards"
        )
        
        if self._can_use_email(lead):
            self.email_handler.send_to_lead(lead, confirmation)
        
        await self.telegram_bot.send_message(
            f"✅ Meeting scheduled with {lead.first_name} {lead.last_name} "
            f"({lead.company_name}) on "
            f"{meeting_time.strftime('%A, %B %d at %I:%M %p')}"
        )
    
    async def _notify_outreach_success(self, lead: Lead, channels: list):
        """Notify about successful outreach"""
        channels_text = " & ".join(channels)
        await self.telegram_bot.notify_new_lead(lead, channels_text)
    
    async def _notify_outreach_failure(self, lead: Lead):
        """Notify about failed outreach"""
        await self.telegram_bot.send_message(
            f"❌ Could not contact {lead.first_name} {lead.last_name} - "
            f"no valid email or phone number"
        )

    def _guess_industry(self, company_name: str) -> str:
        """Simple industry detection"""
        company_lower = company_name.lower()
        
        if any(word in company_lower for word in ['tech', 'software', 'it', 'digital']):
            return "tech companies"
        elif any(word in company_lower for word in ['marketing', 'agency', 'creative']):
            return "marketing agencies"
        elif any(word in company_lower for word in ['construction', 'contracting', 'building']):
            return "construction companies"
        elif any(word in company_lower for word in ['real estate', 'property', 'realty']):
            return "real estate companies"
        elif any(word in company_lower for word in ['consulting', 'advisory']):
            return "consulting firms"
        else:
            return "businesses"
