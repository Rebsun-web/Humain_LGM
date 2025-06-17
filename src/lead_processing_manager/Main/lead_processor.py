# Lead_Processor.py
import re
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
            
            # Try WhatsApp if enabled
            if self._can_use_whatsapp(lead):
                self.logger.debug(f"Attempting WhatsApp outreach to {lead.phone_number}")
                if await self._try_whatsapp_outreach(lead, outreach_message):
                    channels_used.append("WhatsApp")
                    send_success = True
                    self.logger.info(f"WhatsApp sent successfully to {lead.phone_number}")
            
            # Update lead status if any channel succeeded
            if send_success:
                self._update_lead_status(lead, LeadStatus.CONTACTED, next_follow_up_days=2)
                
                with db_session() as db:
                    db.merge(lead)
                    db.commit()
                    self.logger.info(f"Updated lead status to {LeadStatus.CONTACTED}")
            else:
                await self._notify_outreach_failure(lead)
                self.logger.warning(f"No available channels for {lead.first_name} {lead.last_name}")

        except Exception as e:
            self.logger.error(f"Error processing lead {lead.id}: {str(e)}", exc_info=True)
            raise

    async def _handle_lead_time_selection(self, lead: Lead, message: str, channel: CommunicationChannel, db) -> bool:
        """Handle when lead selects a time option (responds with 1, 2, or 3)"""
        
        # Check if this is a number selection (1, 2, 3) or confirmation (yes)
        message_clean = message.strip().lower()
        
        # Handle various types of responses
        selection_index = None
        
        if message_clean in ['1', '2', '3', 'one', 'two', 'three']:
            # Convert to index
            if message_clean in ['1', 'one']:
                selection_index = 0
            elif message_clean in ['2', 'two']:
                selection_index = 1
            elif message_clean in ['3', 'three']:
                selection_index = 2
        elif message_clean in ['yes', 'yeah', 'yep', 'sure', 'okay', 'ok', 'confirm', 'confirmed']:
            # For single option confirmations
            selection_index = 0
        else:
            return False  # Not a time selection
        
        try:
            # Find the pending meeting for this lead
            for meeting_id, meeting_data in self.telegram_bot.pending_meetings.items():
                if (meeting_data.get('lead_id') == lead.id and 
                    meeting_data.get('awaiting_lead_selection')):
                    
                    suggested_times = meeting_data.get('manager_suggested_parsed_times', [])
                    
                    if selection_index < len(suggested_times):
                        selected_time = suggested_times[selection_index]
                        
                        # Create the meeting
                        success = await self.telegram_bot._create_or_update_meeting(
                            lead, selected_time, meeting_id
                        )
                        
                        if success:
                            # Send confirmation
                            confirmation_msg = f"""
                            Perfect!
                            Meeting confirmed for {selected_time.strftime('%A, %B %d at %I:%M %p')}.
                            You'll get a calendar invite shortly. Looking forward to our chat!
                            Any questions? Just reply here.
                            """
                            
                            handler = self._get_channel_handler(channel)
                            if handler:
                                handler.send_to_lead(lead, confirmation_msg)
                                self._store_conversation(db, lead, channel, "outbound", confirmation_msg)
                            
                            # Notify managers
                            await self.telegram_bot.send_message(
                                f"✅ {lead.first_name} selected option {selection_index + 1}. "
                                f"Meeting confirmed for {selected_time.strftime('%A, %B %d at %I:%M %p')}"
                            )
                            
                            # Clean up
                            del self.telegram_bot.pending_meetings[meeting_id]
                            
                            return True
                        else:
                            # Failed to create meeting
                            error_msg = "Sorry, there was an issue scheduling the meeting. Let me check and get back to you."
                            handler = self._get_channel_handler(channel)
                            if handler:
                                handler.send_to_lead(lead, error_msg)
                            return True
                    
                    break
            
            # If we get here, no valid selection found
            return False
            
        except Exception as e:
            self.logger.error(f"Error handling time selection: {e}")
            return False

    # In process_lead_response method, consolidate database operations:
    async def process_lead_response(self, lead: Lead, message: str, channel: CommunicationChannel):
        """Process a response from a lead - UPDATED"""
        try:
            lead_data = {
                'id': lead.id,
                'first_name': lead.first_name,
                'last_name': lead.last_name,
                'company_name': lead.company_name,
                'email': lead.email,
                'phone_number': lead.phone_number
            }
            
            with db_session() as db:
                lead = db.merge(lead)
                
                # Store inbound conversation
                self._store_conversation(db, lead, channel, "inbound", message)
                db.commit()
                
                # Check if this is a time selection response first
                if await self._handle_lead_time_selection(lead, message, channel, db):
                    return  # Time selection handled, exit early
                
                # Otherwise, proceed with normal intent analysis
                intent = self.gpt.analyze_message_intent(message)
                self.logger.info(f"Intent analysis for lead {lead.id}: {intent}")
                
                conversations = self._get_lead_conversations(db, lead)
                
                # Handle meeting scheduling if applicable
                meeting_handled = await self._handle_meeting_flow(
                    lead, message, intent, conversations, channel, db
                )
                
                # If not meeting-related, handle normal conversation flow
                if not meeting_handled:
                    self._update_lead_status_from_intent(lead, intent)
                    
                    reply = self.gpt.generate_reply(lead, conversations, message)
                    
                    handler = self._get_channel_handler(channel)
                    if handler:
                        success = handler.send_to_lead(lead, reply)
                        if not success:
                            self.logger.error(f"Failed to send reply to lead {lead.id}")
                
                # Update conversation summary and last contact
                lead.conversation_summary = self.gpt.summarize_conversation(conversations)
                lead.last_contact_date = datetime.utcnow()
                db.add(lead)
                db.commit()
            
            # Send notifications
            # await self._handle_response_notifications_safe(lead_data, message, intent)
            
        except Exception as e:
            self.logger.error(f"Error processing lead response: {str(e)}", exc_info=True)
            raise

    # async def _handle_response_notifications_safe(self, lead_data: dict, message: str, intent: dict):
    #     """Handle notifications with lead data instead of lead object"""
    #     try:
    #         # Create a simple object-like dict for the telegram bot
    #         class LeadData:
    #             def __init__(self, data):
    #                 self.__dict__.update(data)
            
    #         lead_obj = LeadData(lead_data)
    #         await self.telegram_bot.notify_lead_responded(lead_obj, message, intent.get('sentiment', 'neutral'))
    #     except Exception as e:
    #         self.logger.error(f"Error sending notification: {str(e)}")

    # lead_processor.py - Add this helper method
    def _get_last_bot_message(self, conversations: List[Conversation]) -> Optional[str]:
        """Get the last outbound message from the bot"""
        for conv in reversed(conversations):
            if conv.direction == "outbound":
                return conv.message_content
        return None

    # Update _handle_meeting_flow to check for repeated responses
    async def _handle_meeting_flow(self, lead: Lead, message: str, intent: Dict, conversations: List[Conversation], channel: CommunicationChannel, db) -> bool:
        """Handle the complete meeting scheduling flow with manager approval"""
        
        stage = intent.get('stage', 'general')
        specified_time = intent.get('specified_time') == 'yes'
        confirming_time = intent.get('confirming_time') == 'yes'
        requesting_meeting = intent.get('requesting_meeting') == 'yes'
        
        self.logger.info(f"Meeting flow - Stage: {stage}, Specified: {specified_time}, "
                        f"Confirming: {confirming_time}, Requesting: {requesting_meeting}")
        
        # If lead provided their availability (like in your log: "20th June, 11am-1pm")
        if specified_time and stage == 'scheduling':
            await self._process_lead_availability(lead, message, channel, db)
            return True
        
        # If lead is requesting a meeting but hasn't given times
        elif requesting_meeting and not specified_time:
            await self._ask_for_availability(lead, channel, db)
            return True
        
        # If lead confirms a time we suggested
        elif confirming_time:
            await self._handle_time_confirmation(lead, channel, db)
            return True
        
        return False
    
    async def _handle_availability_fallback(self, lead: Lead, message: str, channel: CommunicationChannel, db):
        """Fallback handler when Telegram fails - use old direct scheduling"""
        self.logger.info(f"Using fallback scheduling for {lead.first_name}")
        
        # Parse the meeting time using existing logic
        meeting_time = await self._parse_meeting_time(message)
        
        if meeting_time:
            # Create calendar event directly
            event_id = self.calendar_handler.create_meeting(
                summary=f"Lead Meeting - {lead.first_name} {lead.last_name}",
                start_time=meeting_time,
                duration_minutes=30,
                attendee_email=lead.email,
                description=self._generate_meeting_description(lead)
            )
            
            if event_id:
                # Store meeting
                meeting = Meeting(
                    lead_id=lead.id,
                    scheduled_time=meeting_time,
                    duration_minutes=30,
                    calendar_event_id=event_id,
                    status='confirmed',
                    notes=f"Auto-scheduled via fallback: {message}"
                )
                db.add(meeting)
                
                lead.status = LeadStatus.MEETING_SCHEDULED
                db.add(lead)
                db.commit()
                
                confirmation_msg = (
                    f"Perfect! Meeting confirmed for "
                    f"{meeting_time.strftime('%A, %B %d at %I:%M %p')}. "
                    f"Calendar invitation sent!"
                )
            else:
                confirmation_msg = (
                    f"Got it! I'll manually add this to my calendar and send you "
                    f"an invitation for {meeting_time.strftime('%A, %B %d at %I:%M %p')}."
                )
        else:
            confirmation_msg = (
                "Thanks for the times! Let me check my calendar and "
                "I'll get back to you with a confirmation shortly."
            )
        
        handler = self._get_channel_handler(channel)
        if handler:
            handler.send_to_lead(lead, confirmation_msg)
            self._store_conversation(db, lead, channel, "outbound", confirmation_msg)

    # Update _process_lead_availability in LeadProcessor.py to prevent multiple meetings
    async def _process_lead_availability(self, lead: Lead, message: str, channel: CommunicationChannel, db):
        """Process when lead provides their availability - SEND TO MANAGERS FOR APPROVAL"""
        self.logger.info(f"Processing availability from {lead.first_name}: {message}")
        
        # Check if lead already has pending meetings and clean them up
        existing_meetings = db.query(Meeting).filter_by(lead_id=lead.id).all()
        if existing_meetings:
            self.logger.info(f"Found {len(existing_meetings)} existing meetings for lead {lead.id}")
            # Note: We'll update the existing one instead of creating multiple
        
        # Parse lead's availability using GPT
        lead_availability = self.gpt.parse_availability_slots(message)
        
        if not lead_availability:
            clarification_msg = (
                "I want to make sure I get the timing right. Could you please provide "
                "2-3 specific times that work for you? For example: 'Monday at 2 PM, "
                "Tuesday morning, or Wednesday at 10 AM'."
            )
            handler = self._get_channel_handler(channel)
            if handler:
                handler.send_to_lead(lead, clarification_msg)
            return
        
        # Find matching slots in calendar
        matching_slots = self.calendar_handler.find_matching_slots(lead_availability)
        
        # Update lead status
        lead.status = LeadStatus.MEETING_REQUESTED
        db.add(lead)
        db.commit()
        
        # Try to send to managers for approval
        telegram_success = False
        try:
            await self.telegram_bot.request_meeting_approval(lead, lead_availability, matching_slots)
            telegram_success = True
            self.logger.info(f"Meeting approval request sent to managers for lead {lead.id}")
            
            ack_msg = (
                f"Thanks {lead.first_name}! I'm checking my calendar against your availability. "
                f"I'll get back to you within the hour with a confirmed time slot."
            )
            
        except Exception as e:
            self.logger.error(f"Telegram failed: {e}")
            telegram_success = False
            
            # Fallback message
            ack_msg = (
                f"Thanks {lead.first_name}! I've noted your availability:\n"
                + "\n".join(
                    [
                        f"• {slot.get('day', 'Unknown')} {slot.get('time', 'Unknown')}"
                        for slot in lead_availability[:3]
                    ]
                )
                + "\n\nLet me check my calendar and I'll confirm a time shortly."
            )
        
        # Send acknowledgment to lead
        handler = self._get_channel_handler(channel)
        if handler:
            handler.send_to_lead(lead, ack_msg)
            self._store_conversation(db, lead, channel, "outbound", ack_msg)
        
        if not telegram_success:
            self.logger.warning(f"Manual intervention needed for lead {lead.id} - Telegram notification failed")

    async def _ask_for_availability(self, lead: Lead, channel: CommunicationChannel, db):
        """Ask lead for their availability"""
        self.logger.info(f"Asking {lead.first_name} for availability")
        
        # Generate availability request using GPT
        availability_request = self.gpt.ask_for_availability(lead)
        
        # Update status
        lead.status = LeadStatus.MEETING_REQUESTED
        db.add(lead)
        
        # Send message
        handler = self._get_channel_handler(channel)
        if handler:
            handler.send_to_lead(lead, availability_request)
            self._store_conversation(db, lead, channel, "outbound", availability_request)

    async def _handle_specific_time_request(self, lead: Lead, message: str, channel: CommunicationChannel, db):
        """Handle when lead specifies a specific meeting time"""
        self.logger.info(f"Handling specific time request from {lead.first_name}: {message}")
        
        # Parse the meeting time
        meeting_time = await self._parse_meeting_time(message)
        
        if meeting_time:
            # For now, assume the time is available (you can add calendar checking later)
            # Create a proper datetime with timezone
            meeting_time = meeting_time.replace(tzinfo=None)  # Remove timezone for now
            
            # Store meeting intent in database first
            meeting = Meeting(
                lead_id=lead.id,
                scheduled_time=meeting_time,
                duration_minutes=30,
                status='tentative',
                notes=f"Meeting requested via {channel.value}: {message}"
            )
            db.add(meeting)
            db.commit()
            
            # Update lead status
            lead.status = LeadStatus.MEETING_SCHEDULED
            db.add(lead)
            db.commit()
            
            # Generate appropriate response
            confirmation_msg = (
                f"Perfect! I've noted down {meeting_time.strftime('%A, %B %d at %I:%M %p')} "
                f"for our meeting. I'll send you a calendar invite shortly with the meeting link. "
                f"Looking forward to discussing how we can help {lead.company_name} generate more leads!"
            )
            
            # TODO: Actually create calendar event here
            # event_id = self.calendar_handler.create_meeting(...)
            
        else:
            # Couldn't parse the time, ask for clarification
            confirmation_msg = (
                f"I want to make sure I get the timing right. Could you please specify "
                f"the exact date and time you'd prefer? For example: 'Friday at 2:30 PM' "
                f"or 'June 21st at 10 AM'."
            )
            lead.status = LeadStatus.MEETING_REQUESTED
            db.add(lead)
            db.commit()
        
        # Send the response
        handler = self._get_channel_handler(channel)
        if handler:
            handler.send_to_lead(lead, confirmation_msg)

    async def _handle_time_confirmation(self, lead: Lead, channel: CommunicationChannel, db):
        """Handle when lead confirms a suggested time"""
        self.logger.info(f"Handling time confirmation from {lead.first_name}")
        
        # Check if we have a pending meeting
        existing_meeting = db.query(Meeting).filter_by(
            lead_id=lead.id
        ).order_by(Meeting.created_at.desc()).first()
        
        if existing_meeting and existing_meeting.status != 'confirmed':
            existing_meeting.status = 'confirmed'
            lead.status = LeadStatus.MEETING_SCHEDULED
            
            confirmation_msg = (
                f"Excellent! 🎉 Meeting confirmed for "
                f"{existing_meeting.scheduled_time.strftime('%A, %B %d at %I:%M %p')}. "
                f"Calendar invitation sent. Looking forward to discussing how we can help "
                f"{lead.company_name}!"
            )
        else:
            # No existing meeting, treat as interest
            lead.status = LeadStatus.INTERESTED
            confirmation_msg = (
                f"Perfect! Let me check my calendar and suggest some specific times. "
                f"I'll get back to you within the hour with options."
            )
        
        handler = self._get_channel_handler(channel)
        if handler:
            handler.send_to_lead(lead, confirmation_msg)
            self._store_conversation(db, lead, channel, "outbound", confirmation_msg)

    async def _handle_general_meeting_request(self, lead: Lead, channel: CommunicationChannel, db):
        """Handle general meeting requests without specific time"""
        self.logger.info(f"Handling general meeting request from {lead.first_name}")
        
        lead.status = LeadStatus.MEETING_REQUESTED
        
        # Get available slots from calendar
        available_slots = self.calendar_handler.get_available_slots(
            duration_minutes=30, days_ahead=5
        )
        
        if available_slots:
            # Present top 3 available slots
            slots_text = "\n".join([
                f"• {slot['display']}" for slot in available_slots[:3]
            ])
            
            reply_msg = (
                f"Great! I'd love to chat. Here are some times that work well:\n\n"
                f"{slots_text}\n\nWhich of these works best for you?"
            )
        else:
            # Fallback if no slots available
            reply_msg = (
                f"I'd love to schedule a call! How does your calendar look "
                f"tomorrow afternoon or early next week?"
            )
        
        handler = self._get_channel_handler(channel)
        if handler:
            handler.send_to_lead(lead, reply_msg)
            self._store_conversation(db, lead, channel, "outbound", reply_msg)

    async def _parse_meeting_time(self, message: str) -> Optional[datetime]:
        """Parse meeting time from natural language using GPT"""
        try:
            # Use GPT to parse the meeting time
            time_info = self.gpt.parse_meeting_time(message)
            
            if time_info and time_info.get('parsed_datetime'):
                return datetime.fromisoformat(time_info.get('parsed_datetime'))
            
            # Fallback to manual parsing
            return self._enhanced_manual_parsing(message)
                
        except Exception as e:
            self.logger.error(f"Error parsing meeting time: {str(e)}")
            return self._enhanced_manual_parsing(message)
        
    def _enhanced_manual_parsing(self, message: str) -> Optional[datetime]:
        """Enhanced manual parsing for common time expressions"""
        message_lower = message.lower()
        now = datetime.now()
        
        # Dictionary for day names to date calculation
        day_mapping = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        
        # Time mapping
        time_mapping = {
            'morning': 9,
            'afternoon': 14,
            'evening': 18
        }
        
        # Parse day
        target_date = None
        for day_name, day_num in day_mapping.items():
            if day_name in message_lower:
                days_ahead = day_num - now.weekday()
                if days_ahead <= 0:  # Target day already happened this week
                    days_ahead += 7
                target_date = now + timedelta(days=days_ahead)
                break
        
        if not target_date:
            if 'tomorrow' in message_lower:
                target_date = now + timedelta(days=1)
            elif 'today' in message_lower:
                target_date = now
            else:
                # Default to next occurrence
                target_date = now + timedelta(days=1)
        
        # Parse time
        hour = 14  # Default to 2 PM
        for time_name, time_hour in time_mapping.items():
            if time_name in message_lower:
                hour = time_hour
                break
        
        # Check for specific times like "12:30", "2pm", etc.
        import re
        time_pattern = r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?'
        match = re.search(time_pattern, message_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            meridiem = match.group(3)
            
            if meridiem == 'pm' and hour < 12:
                hour += 12
            elif meridiem == 'am' and hour == 12:
                hour = 0
        else:
            minute = 0
        
        # Construct the datetime
        meeting_time = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # Make sure it's in the future
        if meeting_time <= now:
            meeting_time += timedelta(days=1)
        
        self.logger.info(f"Parsed meeting time: {meeting_time} from message: {message}")
        return meeting_time

    def _generate_meeting_description(self, lead: Lead) -> str:
        """Generate meeting description"""
        return f"""Lead Generation Discussion

Company: {lead.company_name}
Contact: {lead.first_name} {lead.last_name}
Phone: {lead.phone_number or 'N/A'}
Email: {lead.email or 'N/A'}

Conversation Summary:
{lead.conversation_summary or 'Initial outreach - discussing lead generation services'}

Meeting scheduled via automated system.
"""

    def _store_meeting_in_db(self, db, lead: Lead, event_id: str, meeting_time: datetime):
        """Store meeting details in database"""
        try:
            meeting = Meeting(
                lead_id=lead.id,
                scheduled_time=meeting_time,
                duration_minutes=30,
                calendar_event_id=event_id,
                status='confirmed',
                notes=f"Meeting scheduled via automated conversation on {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            db.add(meeting)
            self.logger.info(f"Meeting stored in database for lead {lead.id}")
            
        except Exception as e:
            self.logger.error(f"Error storing meeting in database: {str(e)}")

    # Keep all your existing helper methods
    def _generate_outreach_message(self, lead: Lead) -> str:
        """Generate personalized outreach message"""
        try:
            industry = self._guess_industry(lead.company_name)
            self.logger.debug(f"Detected industry for {lead.company_name}: {industry}")
            
            if config.USE_TEMPLATES:
                return Templates.get_initial_outreach(lead.first_name, industry, "Dubai")
            else:
                return self.gpt.generate_initial_outreach(lead)
        except Exception as e:
            self.logger.error(f"Error generating outreach message for {lead.id}: {str(e)}", exc_info=True)
            raise

    def _can_use_email(self, lead: Lead) -> bool:
        """Check if email can be used for this lead"""
        return bool(lead.email_verified and lead.email and config.EMAIL_ENABLED)

    def _can_use_whatsapp(self, lead: Lead) -> bool:
        """Check if WhatsApp can be used for this lead"""
        return bool(lead.phone_number and config.WHATSAPP_ENABLED and self.whatsapp_handler)

    async def _try_whatsapp_outreach(self, lead: Lead, message: str) -> bool:
        """Attempt to send WhatsApp message with rate limiting"""
        if not self.whatsapp_handler:
            return False
        
        can_send, reason = self.whatsapp_handler.check_rate_limit()
        if not can_send:
            await self.telegram_bot.send_message(f"⚠️ Cannot send WhatsApp to {lead.first_name}: {reason}")
            return False
        
        return self.whatsapp_handler.send_to_lead(lead, message)

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
        sentiment = intent.get('sentiment', 'neutral')
        requesting_meeting = intent.get('requesting_meeting') == 'yes'
        expressing_interest = intent.get('expressing_interest') == 'yes'
        
        if sentiment == 'negative':
            lead.status = LeadStatus.NOT_INTERESTED
        elif requesting_meeting:
            lead.status = LeadStatus.MEETING_REQUESTED
        elif expressing_interest:
            lead.status = LeadStatus.INTERESTED
        else:
            lead.status = LeadStatus.RESPONDED
        
        self.logger.info(f"Updated lead {lead.id} status to: {lead.status}")

    def _get_lead_conversations(self, db, lead: Lead) -> list:
        """Get all conversations for a lead"""
        return db.query(Conversation).filter_by(lead_id=lead.id).order_by(Conversation.timestamp).all()

    # async def _handle_response_notifications(self, lead: Lead, message: str, intent: Dict):
    #     """Handle notifications after lead response"""
    #     await self.telegram_bot.notify_lead_responded(
    #         lead, message, intent.get('sentiment', 'neutral')
    #     )

    def _get_channel_handler(self, channel: CommunicationChannel):
        """Get the appropriate communication handler for a channel"""
        if channel == CommunicationChannel.EMAIL:
            return self.email_handler
        elif channel == CommunicationChannel.WHATSAPP:
            return self.whatsapp_handler
        return None

    def _update_lead_status(self, lead: Lead, status: LeadStatus, next_follow_up_days: int = None):
        """Update lead status and follow-up date"""
        lead.status = status
        lead.last_contact_date = datetime.utcnow()
        if next_follow_up_days:
            lead.next_follow_up_date = datetime.utcnow() + timedelta(days=next_follow_up_days)

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

    async def _notify_outreach_failure(self, lead: Lead):
        """Notify about failed outreach"""
        await self.telegram_bot.send_message(
            f"❌ Could not contact {lead.first_name} {lead.last_name} - "
            f"no valid email or phone number"
        )

    # Keep your existing follow-up and bulk processing methods
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
            lead, conversations,
            "[SYSTEM: Generate a follow-up message as no response received]"
        )
        
        sent = await self._send_followup_message(lead, follow_up)
        
        if sent:
            self._update_lead_status(lead, LeadStatus.FOLLOW_UP, next_follow_up_days=7)
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

    async def process_bulk_whatsapp_outreach(self):
        """Process bulk WhatsApp outreach to leads"""
        if not (self.whatsapp_handler and config.WHATSAPP_ENABLED):
            self.logger.debug("WhatsApp outreach disabled or handler not available")
            return
        
        with db_session() as db:
            leads = db.query(Lead).filter(
                Lead.status == LeadStatus.NEW,
                Lead.phone_number.isnot(None)
            ).all()

            self.logger.info(f"Found {len(leads)} leads for WhatsApp outreach")

            for lead in leads:
                try:
                    message = self._generate_outreach_message(lead)

                    if await self._try_whatsapp_outreach(lead, message):
                        self._update_lead_status(lead, LeadStatus.CONTACTED, next_follow_up_days=2)
                        db.add(lead)
                        self.logger.info(f"WhatsApp outreach successful for {lead.first_name}")
                    else:
                        self.logger.warning(f"WhatsApp outreach failed for {lead.first_name}")

                except Exception as e:
                    self.logger.error(f"Error in WhatsApp outreach for lead {lead.id}: {str(e)}", exc_info=True)
                    continue