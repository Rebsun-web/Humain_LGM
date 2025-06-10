from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from datetime import datetime, timedelta
from config import config
from models import Lead
from calendar_handler import CalendarHandler


class TelegramBot:
    def __init__(self):
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        self.group_chat_id = config.TELEGRAM_GROUP_CHAT_ID
        self.calendar_handler = CalendarHandler()
        self.pending_meetings = {}  # Store temporary meeting data
    
    async def send_message(self, message: str, reply_markup=None):
        """Send message to the managers group"""
        await self.bot.send_message(
            chat_id=self.group_chat_id,
            text=message,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    async def notify_new_lead(self, lead: Lead):
        """Notify managers about new lead"""
        message = f"""
🆕 <b>New Lead Added</b>

<b>Name:</b> {lead.first_name} {lead.last_name}
<b>Company:</b> {lead.company_name}
<b>Email:</b> {lead.email}
<b>Phone:</b> {lead.phone_number or 'Not provided'}
<b>Website:</b> {lead.company_website}

Initial outreach will be sent automatically.
        """
        await self.send_message(message)
    
    async def notify_lead_responded(self, lead: Lead, response: str, sentiment: str):
        """Notify when a lead responds"""
        emoji = "😊" if sentiment == "positive" else "😐" if sentiment == "neutral" else "😟"
        
        message = f"""
{emoji} <b>Lead Responded</b>

<b>Lead:</b> {lead.first_name} {lead.last_name} ({lead.company_name})
<b>Sentiment:</b> {sentiment}

<b>Their message:</b>
"{response[:200]}{'...' if len(response) > 200 else ''}"

Automated response is being prepared...
        """
        await self.send_message(message)
    
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
    
    # TODO: Implement the logic to change offsets
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
            
            # TODO: Implement the logic for managers to insert their time slots
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
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("suggest_times:"):
            meeting_id = data.split(":")[1]
            await self.show_time_slots(meeting_id)
            
        elif data.startswith("slot:"):
            # Toggle slot selection
            # This is simplified - in production, you'd track selected slots per user
            await query.answer("Time slot selected!")
            
        elif data.startswith("confirm_slots:"):
            meeting_id = data.split(":")[1]
            # Process selected slots and send to lead
            await self.process_meeting_confirmation(meeting_id)
            
        # Add more callback handlers as needed
    
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
    
    def start_bot(self):
        """Start the Telegram bot"""
        application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Start the bot
        application.run_polling()


# Async function to send notifications (use from main app)
async def send_telegram_notification(message: str, reply_markup=None):
    bot = TelegramBot()
    await bot.send_message(message, reply_markup)
