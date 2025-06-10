from datetime import datetime, timedelta
from sqlalchemy import and_
from models import (
    Lead, LeadStatus, Conversation,
    Meeting, SessionLocal, CommunicationChannel
)
from gpt_handler import GPTHandler
from email_handler import EmailHandler
from whatsapp_handler import WhatsAppHandler
from telegram_bot import TelegramBot, send_telegram_notification
from calendar_handler import CalendarHandler


class LeadProcessor:
    def __init__(self):
        self.gpt = GPTHandler()
        self.email_handler = EmailHandler()
        self.whatsapp_handler = WhatsAppHandler()
        self.telegram_bot = TelegramBot()
        self.calendar_handler = CalendarHandler()

    async def process_new_lead(self, lead: Lead):
        """Process a newly added lead"""
        db = SessionLocal()

        try:
            # Generate initial outreach message
            outreach_message = self.gpt.generate_initial_outreach(lead)

            # Determine communication channel
            if lead.email_verified and lead.email:
                # Send via email
                success = self.email_handler.send_lead_email(lead, outreach_message)
                channel = CommunicationChannel.EMAIL
            elif lead.phone_number:
                # Send via WhatsApp
                success = self.whatsapp_handler.send_lead_whatsapp(lead, outreach_message)
                channel = CommunicationChannel.WHATSAPP
            else:
                print(f"No valid contact method for lead {lead.id}")
                return

            if success:
                # Update lead status
                lead.status = LeadStatus.CONTACTED
                lead.last_contact_date = datetime.utcnow()
                lead.next_follow_up_date = datetime.utcnow() + timedelta(days=3)
                db.commit()

                # Notify managers
                await self.telegram_bot.notify_new_lead(lead)

        except Exception as e:
            print(f"Error processing new lead {lead.id}: {e}")
            db.rollback()
        finally:
            db.close()

    async def check_and_process_responses(self):
        """Check for new responses from leads"""
        db = SessionLocal()

        try:
            # Check email responses
            new_emails = self.email_handler.check_inbox()

            for email_data in new_emails:
                # Find lead by email
                lead = db.query(Lead).filter_by(email=email_data['from']).first()

                if lead:
                    await self.process_lead_response(
                        lead, 
                        email_data['body'], 
                        CommunicationChannel.EMAIL
                    )

            # Check WhatsApp responses (if webhook is set up)
            # whatsapp_messages = self.whatsapp_handler.check_messages()
            # Process similarly...

        except Exception as e:
            print(f"Error checking responses: {e}")
        finally:
            db.close()

    async def process_lead_response(self, lead: Lead, message: str, channel: CommunicationChannel):
        """Process a response from a lead"""
        db = SessionLocal()

        try:
            # Store the conversation
            conversation = Conversation(
                lead_id=lead.id,
                channel=channel,
                direction="inbound",
                message_content=message
            )
            db.add(conversation)

            # Analyze message intent
            intent = self.gpt.analyze_message_intent(message)

            # Update lead status based on sentiment
            if intent['sentiment'] == 'negative':
                lead.status = LeadStatus.NOT_INTERESTED
            elif intent['requesting_meeting'] == 'yes':
                lead.status = LeadStatus.MEETING_REQUESTED
            elif intent['expressing_interest'] == 'yes':
                lead.status = LeadStatus.INTERESTED
            else:
                lead.status = LeadStatus.RESPONDED

            # Get conversation history
            conversations = db.query(Conversation).filter_by(
                lead_id=lead.id
            ).order_by(Conversation.timestamp).all()

            # Update conversation summary
            lead.conversation_summary = self.gpt.summarize_conversation(conversations)

            # Generate and send reply
            reply = self.gpt.generate_reply(lead, conversations, message)

            if channel == CommunicationChannel.EMAIL:
                self.email_handler.send_lead_email(lead, reply)
            elif channel == CommunicationChannel.WHATSAPP:
                self.whatsapp_handler.send_lead_whatsapp(lead, reply)

            # Record outbound message
            outbound_conversation = Conversation(
                lead_id=lead.id,
                channel=channel,
                direction="outbound",
                message_content=reply
            )
            db.add(outbound_conversation)

            # Update last contact date
            lead.last_contact_date = datetime.utcnow()

            db.commit()

            # Notify managers
            await self.telegram_bot.notify_lead_responded(lead, message, intent['sentiment'])

            # If meeting requested, ask managers for available times
            if intent['requesting_meeting'] == 'yes':
                await self.telegram_bot.request_meeting_times(lead, message)

        except Exception as e:
            print(f"Error processing lead response: {e}")
            db.rollback()
        finally:
            db.close()

    async def process_follow_ups(self):
        """Process leads that need follow-up"""
        db = SessionLocal()

        try:
            # Find leads that need follow-up
            leads_to_follow_up = db.query(Lead).filter(
                and_(
                    Lead.next_follow_up_date <= datetime.utcnow(),
                    Lead.status.in_([LeadStatus.CONTACTED, LeadStatus.FOLLOW_UP])
                )
            ).all()

            for lead in leads_to_follow_up:
                # Get conversation history
                conversations = db.query(Conversation).filter_by(
                    lead_id=lead.id
                ).order_by(Conversation.timestamp).all()

                # Generate follow-up message
                follow_up = self.gpt.generate_reply(
                    lead, 
                    conversations, 
                    "[SYSTEM: Generate a follow-up message as no response received]"
                )

                # Send follow-up
                if lead.email_verified and lead.email:
                    self.email_handler.send_lead_email(lead, follow_up)
                elif lead.phone_number:
                    self.whatsapp_handler.send_lead_whatsapp(lead, follow_up)

                # Update next follow-up date
                lead.next_follow_up_date = datetime.utcnow() + timedelta(days=7)
                lead.status = LeadStatus.FOLLOW_UP

            db.commit()

        except Exception as e:
            print(f"Error processing follow-ups: {e}")
            db.rollback()
        finally:
            db.close()

    async def schedule_meeting(self, lead_id: int, meeting_time: datetime, duration_minutes: int = 30):
        """Schedule a meeting with a lead"""
        db = SessionLocal()

        try:
            lead = db.query(Lead).filter_by(id=lead_id).first()
            if not lead:
                return

            # Create calendar event
            event_id = self.calendar_handler.create_meeting(
                summary=f"Meeting with {lead.first_name} {lead.last_name} - {lead.company_name}",
                start_time=meeting_time,
                duration_minutes=duration_minutes,
                attendee_email=lead.email,
                description=f"Lead Generation Discussion\n\nLead Summary:\n{lead.conversation_summary}"
            )

            if event_id:
                # Store meeting in database
                meeting = Meeting(
                    lead_id=lead_id,
                    scheduled_time=meeting_time,
                    duration_minutes=duration_minutes,
                    calendar_event_id=event_id,
                    status='confirmed'
                )
                db.add(meeting)

                # Update lead status
                lead.status = LeadStatus.MEETING_SCHEDULED

                db.commit()

                # Send confirmation to lead
                confirmation_message = f"""
                Great! I've scheduled our meeting for {meeting_time.strftime('%A, %B %d at %I:%M %p')}.

                You should receive a calendar invitation shortly. Looking forward to discussing how we can help {lead.company_name} generate more qualified leads.

                Best regards
                """

                if lead.email_verified and lead.email:
                    self.email_handler.send_lead_email(lead, confirmation_message)

                # Notify managers
                await send_telegram_notification(
                    f"✅ Meeting scheduled with {lead.first_name} {lead.last_name} ({lead.company_name}) "
                    f"on {meeting_time.strftime('%A, %B %d at %I:%M %p')}"
                )

        except Exception as e:
            print(f"Error scheduling meeting: {e}")
            db.rollback()
        finally:
            db.close()
