from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters
)
from telegram.error import TelegramError, NetworkError, TimedOut
from telegram.request import HTTPXRequest
from datetime import datetime, timedelta
from typing import Dict, List
import asyncio

from lead_processing_manager.Configs.config import config
from lead_processing_manager.Models.models import (
    Lead, LeadStatus, Conversation, Meeting, CommunicationChannel
)
from lead_processing_manager.Views.calendar_handler import CalendarHandler
from lead_processing_manager.Utils.db_utils import db_session
from lead_processing_manager.Utils.logging_utils import setup_logger
from lead_processing_manager.Views.whatsapp_handler import WhatsAppHandler
from lead_processing_manager.Views.email_handler import EmailHandler


# Standalone function to send notifications
async def send_telegram_notification(message: str, reply_markup=None):
    bot = TelegramBot()
    await bot.send_message(message, reply_markup)


class TelegramBot:
    _instance = None
    _initialized = False
    _application = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TelegramBot, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            try:
                # Create custom request with proper connection pooling
                request = HTTPXRequest(
                    connection_pool_size=16,  # Increase pool size
                    pool_timeout=60.0,        # Increase timeout
                    connect_timeout=30.0,
                    read_timeout=30.0,
                    write_timeout=30.0,
                )
                
                # Initialize bot with custom request
                self.bot = Bot(
                    token=config.TELEGRAM_BOT_TOKEN,
                    request=request
                )
                
            except Exception as e:
                # Fallback to basic bot if HTTPXRequest fails
                print(f"Warning: Could not create custom request handler: {e}")
                self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
            
            self.group_chat_id = config.TELEGRAM_GROUP_CHAT_ID
            self.calendar_handler = CalendarHandler()
            self.pending_meetings = {}
            self._initialized = True
            self.logger = setup_logger(__name__)
    
    async def send_message(self, message: str, reply_markup=None):
        """Send message to the managers group with improved error handling"""
        max_retries = 3
        base_delay = 2
        
        for attempt in range(max_retries):
            try:
                await self.bot.send_message(
                    chat_id=self.group_chat_id,
                    text=message,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
                self.logger.info("Telegram message sent successfully")
                return True  # Success
                
            except (NetworkError, TimedOut) as e:
                self.logger.warning(f"Network error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff: 2, 4, 8 seconds
                    self.logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    self.logger.error("All retry attempts exhausted")
                    
            except TelegramError as e:
                self.logger.error(f"Telegram API error: {e}")
                if "chat not found" in str(e).lower():
                    self.logger.error(f"Chat ID {self.group_chat_id} not found. Please check the group chat ID.")
                return False  # Don't retry on API errors
                
            except Exception as e:
                self.logger.error(f"Unexpected error sending Telegram message: {e}")
                return False  # Don't retry on unexpected errors
        
        return False  # All attempts failed

    async def request_meeting_approval(self, lead: Lead, lead_availability: List[Dict], matching_slots: List[Dict]):
        """Request manager approval for meeting with proposed times"""
        meeting_id = f"approve_{lead.id}_{int(datetime.now().timestamp())}"
        
        # Store meeting context
        self.pending_meetings[meeting_id] = {
            'lead_id': lead.id,
            'lead_availability': lead_availability,
            'matching_slots': matching_slots,
            'requested_at': datetime.now()
        }
        
        # Build message
        availability_text = "\n".join([
            f"• {slot.get('day', 'Unknown')} {slot.get('time', 'Unknown')}" 
            for slot in lead_availability[:5]
        ])
        
        matching_text = "\n".join([
            f"• {slot['display']}" for slot in matching_slots[:3]
        ]) if matching_slots else "❌ No exact matches found in calendar"
        
        message = f"""🔔 <b>Meeting Approval Request</b>

            <b>Lead:</b> {lead.first_name} {lead.last_name}
            <b>Company:</b> {lead.company_name}
            <b>Email:</b> {lead.email}

            <b>Lead's Availability:</b>
            {availability_text}

            <b>Available Calendar Slots:</b>
            {matching_text}

            What would you like to do?
        """
        
        if matching_slots:
            # Show best matching times for approval
            keyboard = []
            for i, slot in enumerate(matching_slots[:3]):
                keyboard.append([InlineKeyboardButton(
                    f"✅ Approve: {slot['display']}", 
                    callback_data=f"approve_time:{meeting_id}:{i}"
                )])
            
            keyboard.append([InlineKeyboardButton(
                "🔄 Suggest Alternatives", 
                callback_data=f"suggest_alt:{meeting_id}"
            )])
            keyboard.append([InlineKeyboardButton(
                "❌ Decline Meeting", 
                callback_data=f"decline:{meeting_id}"
            )])
        else:
            # No matches, ask for manager input
            keyboard = [
                [InlineKeyboardButton("📅 Suggest Times", callback_data=f"manager_suggest:{meeting_id}")],
                [InlineKeyboardButton("❌ Decline Meeting", callback_data=f"decline:{meeting_id}")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send with error handling
        success = await self.send_message(message, reply_markup)
        
        if not success:
            self.logger.error(f"Failed to send meeting approval request for lead {lead.id}")
            # Clean up if failed
            if meeting_id in self.pending_meetings:
                del self.pending_meetings[meeting_id]
            raise Exception("Failed to send Telegram message - all retries exhausted")
        
        return True
    
    async def cleanup(self):
        """Clean up bot resources"""
        if self._application:
            try:
                await self._application.stop()
                await self._application.shutdown()
                self._application = None
            except Exception as e:
                print(f"Error during bot cleanup: {e}")

    # async def notify_lead_responded(self, lead: Lead, response: str, sentiment: str):
    #     """Notify when a lead responds (immediate for all responses)"""
    #     emoji = "😊" if sentiment == "positive" else "😐" if sentiment == "neutral" else "😟"
        
    #     message = f"""
    #         {emoji} <b>Lead Responded</b>

    #         <b>Lead:</b> {lead.first_name} {lead.last_name} ({lead.company_name})
    #         <b>Sentiment:</b> {sentiment}

    #         <b>Their message:</b>
    #         "{response[:200]}{'...' if len(response) > 200 else ''}"

    #         Automated response sent.
    #     """
    #     await self.send_message(message)
    
    async def request_meeting_times(self, lead: Lead, lead_message: str):
        """Request meeting time selection from managers"""
        # Generate meeting ID
        meeting_id = f"meet_{lead.id}_{datetime.now().timestamp()}"
        
        # Store meeting context
        self.pending_meetings[meeting_id] = {
            'lead_id': lead.id,
            'lead_message': lead_message,
            'requested_at': datetime.now()
        }
        
        message = f"""
            🔔 <b>New Meeting Request</b>

            <b>Lead:</b> {lead.first_name} {lead.last_name}
            <b>Company:</b> {lead.company_name}
            <b>Email:</b> {lead.email}

            <b>Conversation Summary:</b>
            {lead.conversation_summary or 'No summary available'}

            <b>Lead says:</b>
            "{lead_message}"

            How would you like to proceed?
        """
        
        keyboard = [
            [InlineKeyboardButton("📅 Suggest Times", callback_data=f"suggest_times:{meeting_id}")],
            [InlineKeyboardButton("❓ Ask Availability", callback_data=f"ask_availability:{meeting_id}")],
            [InlineKeyboardButton("❌ Decline Meeting", callback_data=f"decline_meeting:{meeting_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_message(message, reply_markup)
    
    async def show_time_slots(self, meeting_id: str, day_offset: int = 3):
        """Show available time slots for the next day_offset business days"""
        # Generate time slots
        slots = []
        current_date = datetime.now()
        
        for day_offset in range(1, day_offset + 1):  # Next 3 business days
            date = current_date + timedelta(days=day_offset)
            
            # Skip weekends
            if date.weekday() >= 5:
                continue
            
            day_name = date.strftime("%a %b %d")
            
            # Morning slots
            for hour in [9, 10, 11]:
                slot_id = f"{meeting_id}:{date.strftime('%Y-%m-%d')}:{hour:02d}:00"
                slots.append(InlineKeyboardButton(
                    f"{day_name} {hour}:00",
                    callback_data=f"slot:{slot_id}"
                ))
            
            # Afternoon slots
            for hour in [14, 15, 16]:
                slot_id = f"{meeting_id}:{date.strftime('%Y-%m-%d')}:{hour:02d}:00"
                slots.append(InlineKeyboardButton(
                    f"{day_name} {hour}:00",
                    callback_data=f"slot:{slot_id}"
                ))
        
        # Create keyboard with 3 columns
        keyboard = [slots[i:i+3] for i in range(0, len(slots), 3)]
        keyboard.append([InlineKeyboardButton("✅ Confirm Selection", callback_data=f"confirm_slots:{meeting_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "Select available time slots (you can select multiple):"
        await self.send_message(message, reply_markup)
    
    async def process_meeting_confirmation(self, meeting_id: str):
        """Process meeting confirmation and send to lead"""
        meeting_data = self.pending_meetings.get(meeting_id)
        if not meeting_data:
            await self.send_message("Meeting data not found. Please try again.")
            return
        
        # In production, you'd get the actual selected slots
        # For now, using example slots
        suggested_times = [
            "Monday, June 9th at 10:00 AM",
            "Tuesday, June 10th at 2:00 PM",
            "Wednesday, June 11th at 9:00 AM"
        ]
        
        message = f"""
            ✅ <b>Meeting Times Sent</b>

            The following times have been suggested to the lead:
            {chr(10).join(f'• {time}' for time in suggested_times)}

            You'll be notified when they respond.
        """
        
        await self.send_message(message)
        
        # Clean up
        del self.pending_meetings[meeting_id]
    
    async def whatsapp_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show WhatsApp usage statistics"""
        stats = self.whatsapp_handler.get_usage_stats()
        
        message = f"""
            📱 <b>WhatsApp Usage Statistics</b>

            <b>Daily Usage:</b>
            - Sent: {stats['daily_count']}/{stats['daily_limit']}
            - Remaining: {stats['daily_remaining']}

            <b>Hourly Usage:</b>
            - Sent: {stats['hourly_count']}/{stats['hourly_limit']}
            - Remaining: {stats['hourly_remaining']}

            <b>Total:</b>
            - All-time sent: {stats['total_sent']}
            - Can send now: {'✅ Yes' if stats['can_send'] else '❌ No'}
        """
        
        await update.message.reply_text(message, parse_mode='HTML')

    async def send_daily_lead_summary(self):
        """Send end-of-day summary of lead activities"""
        try:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            
            with db_session() as db:
                # Get leads by category
                newly_contacted = self._get_newly_contacted_leads(db, today, tomorrow)
                in_conversation = self._get_leads_in_conversation(db, today, tomorrow)
                meetings_scheduled = self._get_meetings_scheduled(db, today, tomorrow)
                
                # Get WhatsApp stats
                if hasattr(self, 'whatsapp_handler') and self.whatsapp_handler:
                    whatsapp_stats = self.whatsapp_handler.get_usage_stats()
                else:
                    whatsapp_stats = {'daily_count': 0, 'daily_limit': 0, 'daily_remaining': 0}
                
                # Build summary message
                summary = self._build_daily_summary(
                    newly_contacted, in_conversation, meetings_scheduled, whatsapp_stats
                )
                
                await self.send_message(summary, parse_mode='HTML')
                
        except Exception as e:
            self.logger.error(f"Error sending daily summary: {e}")
            await self.send_message(f"❌ Error generating daily summary: {str(e)}")

    def _get_newly_contacted_leads(self, db, today, tomorrow):
        """Get leads that were contacted today"""
        return db.query(Lead).filter(
            Lead.last_contact_date >= today,
            Lead.last_contact_date < tomorrow,
            Lead.status.in_([LeadStatus.CONTACTED, LeadStatus.FOLLOW_UP])
        ).all()

    def _get_leads_in_conversation(self, db, today, tomorrow):
        """Get leads that had conversations today"""
        # Get leads that received responses today
        conversation_lead_ids = db.query(Conversation.lead_id).filter(
            Conversation.timestamp >= today,
            Conversation.timestamp < tomorrow,
            Conversation.direction == 'inbound'
        ).distinct().subquery()
        
        return db.query(Lead).filter(
            Lead.id.in_(conversation_lead_ids),
            Lead.status.in_([
                LeadStatus.RESPONDED,
                LeadStatus.INTERESTED,
                LeadStatus.MEETING_REQUESTED
            ])
        ).all()

    def _get_meetings_scheduled(self, db, today, tomorrow):
        """Get meetings that were scheduled today"""
        meeting_lead_ids = db.query(Meeting.lead_id).filter(
            Meeting.created_at >= today,
            Meeting.created_at < tomorrow
        ).distinct().subquery()
        
        return db.query(Lead).filter(
            Lead.id.in_(meeting_lead_ids),
            Lead.status.in_([
                LeadStatus.MEETING_SCHEDULED
            ])
        ).all()

    def _build_daily_summary(self, newly_contacted, in_conversation, meetings_scheduled, whatsapp_stats):
        """Build the daily summary message"""
        summary = f"""
            📊 <b>Daily Lead Summary - {datetime.now().strftime('%B %d, %Y')}</b>
        """

        # Newly Contacted Leads
        if newly_contacted:
            summary += f"🆕 <b>Newly Contacted ({len(newly_contacted)}):</b>\n"
            for lead in newly_contacted:
                channels = self._get_contact_channels(lead)
                summary += f"• <b>{lead.first_name} {lead.last_name}</b> ({lead.company_name}) - {channels}\n"
            summary += "\n"
        else:
            summary += "🆕 <b>Newly Contacted:</b> None\n\n"

        # In Conversation
        if in_conversation:
            summary += f"💬 <b>In Conversation ({len(in_conversation)}):</b>\n"
            for lead in in_conversation:
                last_response = self._get_last_response_time(lead)
                summary += f"• <b>{lead.first_name} {lead.last_name}</b> ({lead.company_name}) - {lead.status.value}\n"
                if last_response:
                    summary += f"  └ Last response: {last_response.strftime('%I:%M %p')}\n"
            summary += "\n"
        else:
            summary += "💬 <b>In Conversation:</b> None\n\n"

        # Meetings Scheduled
        if meetings_scheduled:
            summary += f"🗓️ <b>Meetings Scheduled ({len(meetings_scheduled)}):</b>\n"
            for lead in meetings_scheduled:
                meeting_time = self._get_meeting_time(lead)
                summary += f"• <b>{lead.first_name} {lead.last_name}</b> ({lead.company_name})\n"
                if meeting_time:
                    summary += f"  └ Meeting: {meeting_time.strftime('%A, %B %d at %I:%M %p')}\n"
            summary += "\n"
        else:
            summary += "🗓️ <b>Meetings Scheduled:</b> None\n\n"

        # WhatsApp Usage Stats
        summary += f"""📱 <b>WhatsApp Usage:</b>
        - Sent today: {whatsapp_stats['daily_count']}/{whatsapp_stats['daily_limit']}
        - Remaining: {whatsapp_stats['daily_remaining']}
        """

        # Overall stats
        total_activity = len(newly_contacted) + len(in_conversation) + len(meetings_scheduled)
        if total_activity > 0:
            summary += f"✅ <b>Total lead activities today: {total_activity}</b>"
        else:
            summary += "📋 <b>No lead activities today</b>"

        return summary

    def _get_contact_channels(self, lead):
        """Get the channels used to contact this lead"""
        with db_session() as db:
            conversations = db.query(Conversation).filter(
                Conversation.lead_id == lead.id,
                Conversation.direction == 'outbound'
            ).all()
            
            channels = set()
            for conv in conversations:
                if conv.channel.value == 'email':
                    channels.add('Email')
                elif conv.channel.value == 'whatsapp':
                    channels.add('WhatsApp')
            
            return ' & '.join(channels) if channels else 'Unknown'

    def _get_last_response_time(self, lead):
        """Get the time of the last inbound message from this lead"""
        with db_session() as db:
            last_conversation = db.query(Conversation).filter(
                Conversation.lead_id == lead.id,
                Conversation.direction == 'inbound'
            ).order_by(Conversation.timestamp.desc()).first()
            
            return last_conversation.timestamp if last_conversation else None

    def _get_meeting_time(self, lead):
        """Get the scheduled meeting time for this lead"""
        with db_session() as db:
            meeting = db.query(Meeting).filter(
                Meeting.lead_id == lead.id
            ).order_by(Meeting.created_at.desc()).first()
            
            return meeting.scheduled_time if meeting else None
        
    # Add to telegram_bot.py
    async def request_meeting_approval(self, lead: Lead, lead_availability: List[Dict], matching_slots: List[Dict]):
        """Request manager approval for meeting with proposed times"""
        meeting_id = f"approve_{lead.id}_{datetime.now().timestamp()}"
        
        # Store meeting context
        self.pending_meetings[meeting_id] = {
            'lead_id': lead.id,
            'lead_availability': lead_availability,
            'matching_slots': matching_slots,
            'requested_at': datetime.now()
        }
        
        # Build message
        message = f"""
            🔔 <b>Meeting Approval Request</b>

            <b>Lead:</b> {lead.first_name} {lead.last_name}
            <b>Company:</b> {lead.company_name}
            <b>Email:</b> {lead.email}

            <b>Lead's Availability:</b>
            {chr(10).join([f"• {slot.get('day', 'Unknown')} {slot.get('time', 'Unknown')}" for slot in lead_availability[:5]])}

            <b>Matching Calendar Slots:</b>
            {chr(10).join([f"• {slot['display']}" for slot in matching_slots[:3]]) if matching_slots else "No exact matches found"}
        """
        
        if matching_slots:
            # Show best matching times for approval
            keyboard = []
            for i, slot in enumerate(matching_slots[:3]):
                keyboard.append([InlineKeyboardButton(
                    f"✅ Approve: {slot['display']}", 
                    callback_data=f"approve_time:{meeting_id}:{i}"
                )])
            
            keyboard.append([InlineKeyboardButton(
                "🔄 Suggest Alternatives", 
                callback_data=f"suggest_alt:{meeting_id}"
            )])
            keyboard.append([InlineKeyboardButton(
                "❌ Decline Meeting", 
                callback_data=f"decline:{meeting_id}"
            )])
        else:
            # No matches, ask for manager input
            keyboard = [
                [InlineKeyboardButton("📅 Suggest Times", callback_data=f"manager_suggest:{meeting_id}")],
                [InlineKeyboardButton("❌ Decline Meeting", callback_data=f"decline:{meeting_id}")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self.send_message(message, reply_markup)

    async def handle_meeting_approval_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle manager approval/rejection callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("approve_time:"):
            _, meeting_id, slot_index = data.split(":")
            await self.process_time_approval(meeting_id, int(slot_index))
            
        elif data.startswith("suggest_alt:"):
            meeting_id = data.split(":")[1]
            await self.show_alternative_times(meeting_id)
            
        elif data.startswith("manager_suggest:"):
            meeting_id = data.split(":")[1]
            await self.request_manager_time_input(meeting_id)
            
        elif data.startswith("decline:"):
            meeting_id = data.split(":")[1]
            await self.process_meeting_decline(meeting_id)

    # Update the process_time_approval method in telegram_bot.py
    async def process_time_approval(self, meeting_id: str, slot_index: int):
        """Process manager's approval of a specific time"""
        self.logger.info(f"Starting process_time_approval for meeting_id: {meeting_id}, slot_index: {slot_index}")
        
        meeting_data = self.pending_meetings.get(meeting_id)
        if not meeting_data:
            self.logger.error(f"No meeting data found for meeting_id: {meeting_id}")
            await self.send_message("❌ Meeting data expired. Please start over.")
            return
        
        # Get the approved slot
        matching_slots = meeting_data.get('matching_slots', [])
        if slot_index >= len(matching_slots):
            self.logger.error(f"Invalid slot index {slot_index}, only {len(matching_slots)} slots available")
            await self.send_message("❌ Invalid time slot selected.")
            return
        
        approved_slot = matching_slots[slot_index]
        lead_id = meeting_data['lead_id']
        
        self.logger.info(f"Approved slot: {approved_slot}")
        
        try:
            with db_session() as db:
                lead = db.query(Lead).get(lead_id)
                if not lead:
                    self.logger.error(f"Lead not found with ID: {lead_id}")
                    await self.send_message("❌ Lead not found.")
                    return
                
                # Check for existing meeting for this lead
                existing_meeting = db.query(Meeting).filter_by(
                    lead_id=lead.id
                ).order_by(Meeting.created_at.desc()).first()
                
                # Delete old calendar event if it exists
                if existing_meeting and existing_meeting.calendar_event_id:
                    try:
                        self.calendar_handler.service.events().delete(
                            calendarId='primary',
                            eventId=existing_meeting.calendar_event_id
                        ).execute()
                        self.logger.info(f"Deleted old calendar event: {existing_meeting.calendar_event_id}")
                    except Exception as e:
                        self.logger.warning(f"Could not delete old calendar event: {e}")
                
                # Create new calendar event
                self.logger.info(f"Creating calendar event for {approved_slot['proposed_time']}")
                
                event_id = self.calendar_handler.create_meeting(
                    summary=f"Lead Meeting - {lead.first_name} {lead.last_name}",
                    start_time=approved_slot['proposed_time'],
                    duration_minutes=30,
                    attendee_email=lead.email,
                    description=self._generate_meeting_description(lead)
                )
                
                self.logger.info(f"Calendar event creation result: {event_id}")
                
                if event_id:
                    if existing_meeting:
                        # Update existing meeting
                        existing_meeting.scheduled_time = approved_slot['proposed_time']
                        existing_meeting.calendar_event_id = event_id
                        existing_meeting.status = 'confirmed'
                        existing_meeting.notes = f"Updated via manager approval on {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                        self.logger.info(f"Updated existing meeting ID: {existing_meeting.id}")
                    else:
                        # Create new meeting
                        meeting = Meeting(
                            lead_id=lead.id,
                            scheduled_time=approved_slot['proposed_time'],
                            duration_minutes=30,
                            calendar_event_id=event_id,
                            status='confirmed'
                        )
                        db.add(meeting)
                        self.logger.info("Created new meeting record")
                    
                    # Update lead status
                    lead.status = LeadStatus.MEETING_SCHEDULED
                    db.add(lead)
                    db.commit()
                    
                    self.logger.info("Meeting saved to database successfully")
                    
                    # Send confirmation to lead
                    await self.send_confirmation_to_lead(lead, approved_slot['proposed_time'])
                    
                    # Notify managers
                    action = "updated" if existing_meeting else "scheduled"
                    success_msg = f"✅ Meeting {action} and confirmed with {lead.first_name} for {approved_slot['display']}"
                    await self.send_message(success_msg)
                    self.logger.info("Process completed successfully")
                    
                else:
                    self.logger.error("Calendar event creation returned None")
                    await self.send_message("❌ Failed to create calendar event. Please try manually.")
                    
        except Exception as e:
            self.logger.error(f"Error in process_time_approval: {e}", exc_info=True)
            await self.send_message(f"❌ Error scheduling meeting: {str(e)}")
        
        # Clean up
        if meeting_id in self.pending_meetings:
            del self.pending_meetings[meeting_id]
            self.logger.info(f"Cleaned up meeting data for {meeting_id}")

    # Add/update this method in telegram_bot.py
    async def send_confirmation_to_lead(self, lead: Lead, meeting_time: datetime):
        """Send meeting confirmation back to the lead via WhatsApp"""
        confirmation_msg = f"""
        Perfect!
        Meeting confirmed for {meeting_time.strftime('%A, %B %d at %I:%M %p')}.
        You'll get a calendar invite shortly. Looking forward to our chat!
        Any questions? Just reply here.
        """
        
        try:
            # Find the last channel they used
            with db_session() as db:
                last_conversation = db.query(Conversation).filter_by(
                    lead_id=lead.id,
                    direction='inbound'
                ).order_by(Conversation.timestamp.desc()).first()
                
                if last_conversation and last_conversation.channel == CommunicationChannel.WHATSAPP:
                    whatsapp_handler = WhatsAppHandler()
                    
                    success = whatsapp_handler.send_to_lead(lead, confirmation_msg)
                    if success:
                        self.logger.info(f"WhatsApp confirmation sent to {lead.first_name}")
                        
                        # Store the conversation
                        conversation = Conversation(
                            lead_id=lead.id,
                            channel=CommunicationChannel.WHATSAPP,
                            direction="outbound",
                            message_content=confirmation_msg
                        )
                        db.add(conversation)
                        db.commit()
                    else:
                        self.logger.error(f"Failed to send WhatsApp confirmation to {lead.first_name}")
                        
                else:
                    self.logger.warning(f"No WhatsApp conversation found for lead {lead.id}")
                    
        except Exception as e:
            self.logger.error(f"Error sending confirmation to lead: {e}")

    async def show_alternative_times(self, meeting_id: str):
        """Show alternative time suggestions when exact matches don't work"""
        meeting_data = self.pending_meetings.get(meeting_id)
        if not meeting_data:
            await self.send_message("❌ Meeting data expired. Please start over.")
            return
        
        try:
            # Get lead's preferred times to suggest alternatives around them
            lead_availability = meeting_data['lead_availability']
            alternative_slots = []
            
            # Generate alternatives around each of the lead's preferred times
            for slot in lead_availability[:2]:  # Use first 2 preferred times
                if slot.get('parsed_datetime'):
                    preferred_time = datetime.fromisoformat(slot['parsed_datetime'])
                    alternatives = self.calendar_handler.suggest_alternative_times(
                        preferred_time, num_suggestions=2
                    )
                    alternative_slots.extend(alternatives)
            
            # Remove duplicates and sort
            seen_times = set()
            unique_alternatives = []
            for slot in alternative_slots:
                time_key = slot['time'].strftime('%Y-%m-%d %H:%M')
                if time_key not in seen_times:
                    seen_times.add(time_key)
                    unique_alternatives.append(slot)
            
            unique_alternatives = unique_alternatives[:5]  # Limit to 5 options
            
            if unique_alternatives:
                message = f"""
                    🔄 <b>Alternative Time Suggestions</b>

                    Based on the lead's preferences, here are available alternatives:

                    {chr(10).join([f"• {slot['display']}" for slot in unique_alternatives])}

                    Select which times to offer:
                """
                
                # Create buttons for each alternative
                keyboard = []
                for i, slot in enumerate(unique_alternatives):
                    keyboard.append([InlineKeyboardButton(
                        f"✅ {slot['display']}", 
                        callback_data=f"select_alt:{meeting_id}:{i}"
                    )])
                
                keyboard.append([InlineKeyboardButton(
                    "📝 Custom Time Input", 
                    callback_data=f"custom_time:{meeting_id}"
                )])
                keyboard.append([InlineKeyboardButton(
                    "❌ Cancel Meeting", 
                    callback_data=f"decline:{meeting_id}"
                )])
                
                # Update pending meeting data with alternatives
                meeting_data['alternative_slots'] = unique_alternatives
                self.pending_meetings[meeting_id] = meeting_data
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await self.send_message(message, reply_markup)
                
            else:
                # No alternatives found, ask for manual input
                await self.request_manager_time_input(meeting_id)
                
        except Exception as e:
            self.logger.error(f"Error showing alternative times: {e}")
            await self.send_message(f"❌ Error generating alternatives: {str(e)}")

    async def request_manager_time_input(self, meeting_id: str):
        """Request manager to manually input meeting times"""
        meeting_data = self.pending_meetings.get(meeting_id)
        if not meeting_data:
            await self.send_message("❌ Meeting data expired. Please start over.")
            return
        
        lead_id = meeting_data['lead_id']
        
        with db_session() as db:
            lead = db.query(Lead).get(lead_id)
            
            message = f"""
                📝 <b>Manual Time Input Required</b>

                <b>Lead:</b> {lead.first_name} {lead.last_name} ({lead.company_name})

                <b>Lead's Original Availability:</b>
                {chr(10).join([f"• {slot.get('day', 'Unknown')} {slot.get('time', 'Unknown')}" for slot in meeting_data['lead_availability'][:5]])}

                <b>Instructions:</b>
                Please reply to this message with 2-3 specific times you can offer the lead.

                <b>Format:</b> 
                "Monday June 24 at 2:00 PM, Tuesday June 25 at 10:00 AM, Wednesday June 26 at 3:30 PM"

                The system will send these options to the lead automatically.
            """
        
        keyboard = [
            [InlineKeyboardButton("❌ Cancel Meeting Instead", callback_data=f"decline:{meeting_id}")],
            [InlineKeyboardButton("🔄 Try Auto-Suggest Again", callback_data=f"suggest_alt:{meeting_id}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Mark this meeting as waiting for manual input
        meeting_data['awaiting_manual_input'] = True
        meeting_data['manual_input_requested_at'] = datetime.now()
        self.pending_meetings[meeting_id] = meeting_data
        
        await self.send_message(message, reply_markup)

    async def process_meeting_decline(self, meeting_id: str):
        """Process when manager declines the meeting"""
        meeting_data = self.pending_meetings.get(meeting_id)
        if not meeting_data:
            await self.send_message("❌ Meeting data expired.")
            return
        
        lead_id = meeting_data['lead_id']
        
        try:
            with db_session() as db:
                lead = db.query(Lead).get(lead_id)
                
                # Update lead status
                lead.status = LeadStatus.NOT_INTERESTED
                lead.notes = f"Meeting declined by manager on {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                db.add(lead)
                db.commit()
                
                # Send polite decline message to lead
                decline_msg = (
                    f"Hi {lead.first_name}, thanks for your interest in scheduling a meeting. "
                    f"Unfortunately, our calendar is quite full at the moment and we won't be able "
                    f"to accommodate a meeting in the near future. We'll keep your information on "
                    f"file and reach out if anything changes. Thanks for understanding!"
                )
                
                # Determine which channel to use
                last_conversation = db.query(Conversation).filter_by(
                    lead_id=lead.id,
                    direction='inbound'
                ).order_by(Conversation.timestamp.desc()).first()
                
                if last_conversation:
                    channel = last_conversation.channel
                    if channel == CommunicationChannel.WHATSAPP and hasattr(self, 'whatsapp_handler'):
                        self.whatsapp_handler.send_to_lead(lead, decline_msg)
                    elif channel == CommunicationChannel.EMAIL and hasattr(self, 'email_handler'):
                        self.email_handler.send_to_lead(lead, decline_msg)
                    
                    # Record the conversation
                    conversation = Conversation(
                        lead_id=lead.id,
                        channel=channel,
                        direction="outbound",
                        message_content=decline_msg
                    )
                    db.add(conversation)
                    db.commit()
                
                # Notify managers
                await self.send_message(f"❌ Meeting with {lead.first_name} {lead.last_name} declined and polite response sent.")
                
        except Exception as e:
            self.logger.error(f"Error processing meeting decline: {e}")
            await self.send_message(f"❌ Error declining meeting: {str(e)}")
        
        # Clean up
        if meeting_id in self.pending_meetings:
            del self.pending_meetings[meeting_id]

    # Also add this method to handle alternative time selection
    async def handle_alternative_selection(self, meeting_id: str, slot_index: int):
        """Handle when manager selects an alternative time"""
        meeting_data = self.pending_meetings.get(meeting_id)
        if not meeting_data:
            await self.send_message("❌ Meeting data expired. Please start over.")
            return
        
        alternative_slots = meeting_data.get('alternative_slots', [])
        if slot_index >= len(alternative_slots):
            await self.send_message("❌ Invalid time slot selected.")
            return
        
        selected_slot = alternative_slots[slot_index]
        lead_id = meeting_data['lead_id']
        
        try:
            with db_session() as db:
                lead = db.query(Lead).get(lead_id)
                
                # Create calendar event
                event_id = self.calendar_handler.create_meeting(
                    summary=f"Lead Meeting - {lead.first_name} {lead.last_name}",
                    start_time=selected_slot['time'],
                    duration_minutes=30,
                    attendee_email=lead.email,
                    description=self._generate_meeting_description(lead)
                )
                
                if event_id:
                    # Store in database
                    meeting = Meeting(
                        lead_id=lead.id,
                        scheduled_time=selected_slot['time'],
                        duration_minutes=30,
                        calendar_event_id=event_id,
                        status='confirmed'
                    )
                    db.add(meeting)
                    
                    # Update lead status
                    lead.status = LeadStatus.MEETING_SCHEDULED
                    db.add(lead)
                    db.commit()
                    
                    # Send confirmation to lead
                    await self.send_alternative_time_to_lead(lead, selected_slot['time'])
                    
                    # Notify managers
                    await self.send_message(f"✅ Alternative meeting time scheduled with {lead.first_name} for {selected_slot['display']}")
                    
                else:
                    await self.send_message("❌ Failed to create calendar event. Please try manually.")
                    
        except Exception as e:
            await self.send_message(f"❌ Error scheduling alternative meeting: {str(e)}")
        
        # Clean up
        del self.pending_meetings[meeting_id]

    async def send_alternative_time_to_lead(self, lead: Lead, meeting_time: datetime):
        """Send alternative meeting time to lead for confirmation"""
        time_msg = (
            f"Hi {lead.first_name}, thanks for your flexibility! "
            f"I have an opening on {meeting_time.strftime('%A, %B %d at %I:%M %p')} "
            f"that should work well for our discussion.\n\n"
            f"Does this time work for you? If so, I'll send you a calendar invitation right away!"
        )
        
        # Send via their preferred channel
        with db_session() as db:
            last_conversation = db.query(Conversation).filter_by(
                lead_id=lead.id,
                direction='inbound'
            ).order_by(Conversation.timestamp.desc()).first()
            
            if last_conversation:
                channel = last_conversation.channel
                if channel == CommunicationChannel.WHATSAPP and hasattr(self, 'whatsapp_handler'):
                    self.whatsapp_handler.send_to_lead(lead, time_msg)
                elif channel == CommunicationChannel.EMAIL and hasattr(self, 'email_handler'):
                    self.email_handler.send_to_lead(lead, time_msg)

    def _extract_meeting_id(self, data: str) -> str:
        """
        Extracts the meeting_id from the callback data string.
        Assumes the format is 'action:meeting_id' or similar.
        """
        parts = data.split(":")
        if len(parts) > 1:
            return parts[1]
        return ""

    # Update the existing handle_callback method to include the new callbacks:
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks - UPDATED VERSION"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        self.logger.info(f"Received callback data: {data}")

        meeting_id = self._extract_meeting_id(data)

        if meeting_id:
            if meeting_id not in self.pending_meetings:
                await query.edit_message_text("✅ This meeting has already been processed.")
                return
            
            if self.pending_meetings[meeting_id].get('processing', False):
                await query.answer("⏳ This request is already being processed...", show_alert=True)
                return
            
            # Mark as processing
            self.pending_meetings[meeting_id]['processing'] = True
        
        if data.startswith("suggest_times:"):
            meeting_id = data.split(":")[1]
            await self.show_time_slots(meeting_id)
            
        elif data.startswith("slot:"):
            # Toggle slot selection
            await query.answer("Time slot selected!")
            
        elif data.startswith("confirm_slots:"):
            meeting_id = data.split(":")[1]
            await self.process_meeting_confirmation(meeting_id)
            
        elif data.startswith("approve_time:"):
            _, meeting_id, slot_index = data.split(":")
        
            # Check if this meeting is already being processed
            if meeting_id not in self.pending_meetings:
                await self.send_message("✅ This meeting has already been processed.")
                return
            
            # Mark as processing to prevent double-clicks
            self.pending_meetings[meeting_id]['processing'] = True
            
            self.logger.info(f"Processing time approval: meeting_id={meeting_id}, slot_index={slot_index}")
            try:
                await self.process_time_approval(meeting_id, int(slot_index))
            except Exception as e:
                self.logger.error(f"Error in process_time_approval: {e}", exc_info=True)
                await self.send_message(f"❌ Error processing approval: {str(e)}")
                # Reset processing flag on error
                if meeting_id in self.pending_meetings:
                    self.pending_meetings[meeting_id]['processing'] = False
            
        elif data.startswith("suggest_alt:"):
            meeting_id = data.split(":")[1]
            await self.show_alternative_times(meeting_id)
            
        elif data.startswith("select_alt:"):
            _, meeting_id, slot_index = data.split(":")
            await self.handle_alternative_selection(meeting_id, int(slot_index))
            
        elif data.startswith("custom_time:"):
            meeting_id = data.split(":")[1]
            await self.request_manager_time_input(meeting_id)
            
        elif data.startswith("manager_suggest:"):
            meeting_id = data.split(":")[1]
            await self.request_manager_time_input(meeting_id)
            
        elif data.startswith("decline:"):
            meeting_id = data.split(":")[1]
            await self.process_meeting_decline(meeting_id)

    # Also add this helper method
    def _generate_meeting_description(self, lead: Lead) -> str:
        """Generate meeting description for calendar events"""
        return f"""Lead Generation Discussion

            Company: {lead.company_name}
            Contact: {lead.first_name} {lead.last_name}
            Phone: {lead.phone_number or 'N/A'}
            Email: {lead.email or 'N/A'}

            Conversation Summary:
            {lead.conversation_summary or 'Initial outreach - discussing lead generation services'}

            Meeting scheduled via automated system on {datetime.now().strftime('%Y-%m-%d %H:%M')}.
        """
    
    # Complete the handle_manual_time_input method in telegram_bot.py
    async def handle_manual_time_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle manual time input from managers"""
        if update.message.chat.id != int(self.group_chat_id):
            return
        
        message_text = update.message.text
        self.logger.info(f"Received manual time input: {message_text}")
        
        # Check for pending manual input
        pending_meeting = None
        meeting_id = None
        
        for mid, data in self.pending_meetings.items():
            if data.get('awaiting_manual_input') and \
            (datetime.now() - data.get('manual_input_requested_at', datetime.now())).total_seconds() < 3600:
                pending_meeting = data
                meeting_id = mid
                break
        
        if not pending_meeting:
            self.logger.info("No pending manual input found")
            return
        
        try:
            # Parse the manager's time suggestions using GPT
            from lead_processing_manager.Views.gpt_handler import GPTHandler
            gpt = GPTHandler()
            suggested_times = gpt.parse_availability_slots(message_text)
            
            self.logger.info(f"Parsed {len(suggested_times)} time suggestions: {suggested_times}")
            
            if suggested_times:
                lead_id = pending_meeting['lead_id']
                
                with db_session() as db:
                    lead = db.query(Lead).get(lead_id)
                    if not lead:
                        await update.message.reply_text("❌ Lead not found.")
                        return
                    
                    # Format the times for the lead
                    time_options = []
                    parsed_times = []
                    
                    for slot in suggested_times[:3]:  # Limit to 3 options
                        if slot.get('parsed_datetime'):
                            try:
                                time_obj = datetime.fromisoformat(slot['parsed_datetime'])
                                # Skip past times
                                if time_obj > datetime.now():
                                    time_options.append(time_obj.strftime('%A, %B %d at %I:%M %p'))
                                    parsed_times.append(time_obj)
                            except Exception as e:
                                self.logger.warning(f"Could not parse time {slot['parsed_datetime']}: {e}")
                                continue
                    
                    if time_options:
                        # Send options to lead
                        if len(time_options) == 1:
                            options_msg = (
                                f"Hi {lead.first_name}! I have this time available:\n\n"
                                f"• {time_options[0]}\n\n"
                                f"Does this work for you? Just reply 'yes' to confirm!"
                            )
                        else:
                            options_msg = (
                                f"Hi {lead.first_name}! I have these times available:\n\n"
                                f"{chr(10).join([f'{i+1}. {time}' for i, time in enumerate(time_options)])}\n\n"
                                f"Which works best for you? Just reply with the number (1, 2, or 3)."
                            )
                        
                        # Send via WhatsApp
                        from lead_processing_manager.Views.whatsapp_handler import WhatsAppHandler
                        whatsapp_handler = WhatsAppHandler()
                        success = whatsapp_handler.send_to_lead(lead, options_msg)
                        
                        if success:
                            # Store the suggested times for when lead responds
                            pending_meeting['manager_suggested_times'] = suggested_times
                            pending_meeting['manager_suggested_parsed_times'] = parsed_times
                            pending_meeting['manager_suggested_options'] = time_options
                            pending_meeting['awaiting_manual_input'] = False
                            pending_meeting['awaiting_lead_selection'] = True
                            self.pending_meetings[meeting_id] = pending_meeting
                            
                            # Store conversation in database
                            conversation = Conversation(
                                lead_id=lead.id,
                                channel=CommunicationChannel.WHATSAPP,
                                direction="outbound",
                                message_content=options_msg
                            )
                            db.add(conversation)
                            db.commit()
                            
                            await update.message.reply_text(
                                f"✅ Time options sent to {lead.first_name}:\n"
                                f"{chr(10).join([f'• {time}' for time in time_options])}\n\n"
                                f"I'll notify you when they respond."
                            )
                            
                            self.logger.info(f"Successfully sent {len(time_options)} options to lead {lead.first_name}")
                        else:
                            await update.message.reply_text(
                                f"❌ Failed to send WhatsApp message to {lead.first_name}. "
                                f"Please try again or contact them manually."
                            )
                    else:
                        await update.message.reply_text(
                            "❌ Could not parse valid future times. Please use format like: "
                            "'Monday June 24 at 2:00 PM, Tuesday June 25 at 10:00 AM'"
                        )
            else:
                await update.message.reply_text(
                    "❌ Could not understand the time format. Please try again with specific dates and times."
                )
                
        except Exception as e:
            self.logger.error(f"Error processing manual time input: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error processing times: {str(e)}")

    # Also make sure the setup_bot method includes message handling
    def setup_bot(self):
        """Set up the Telegram bot application"""
        if self._application:
            asyncio.create_task(self.cleanup())
        
        self._application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        
        # Add handlers
        self._application.add_handler(CallbackQueryHandler(self.handle_callback))
        self._application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_manual_time_input))
        
        return self._application