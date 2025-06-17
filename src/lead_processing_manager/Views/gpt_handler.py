# GPT_Handler.py
import openai
import json
import datetime
from typing import Dict, List, Any
from lead_processing_manager.Configs.config import config
from lead_processing_manager.Models.models import Lead, Conversation
from lead_processing_manager.Utils.logging_utils import setup_logger

openai.api_key = config.OPENAI_API_KEY


class GPTHandler:
    def __init__(self):
        self.client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        self.logger = setup_logger(__name__)

    def generate_initial_outreach(self, lead: Lead) -> str:
        """Generate personalized initial outreach using a proven formula."""
        industry = self._guess_industry(lead.company_name, lead.company_website)
        prompt = (
            f"Create a SHORT, CASUAL cold email using this exact formula:\n\n"
            f"1. {{Opener}} - Direct, no pleasantries\n"
            f"2. {{Value statement}} - Specific to their niche\n"
            f"3. {{Permission to explain}} - Ask for 20-30 seconds\n"
            f"4. Keep TOTAL email under 100 words\n\n"
            f"Lead info:\n"
            f"- Name: {lead.first_name}\n"
            f"- Company: {lead.company_name}\n"
            f"- Industry: {industry}\n"
            f"- Location: Dubai/UAE\n\n"
            f"Use this structure:\n"
            f"\"Hi {lead.first_name},\n\n"
            f"We partner with [specific niche] companies in [location] who are prioritizing growth "
            f"and guarantee to add £100k/month in new revenue over 6 months on a zero risk basis.\n\n"
            f"Can I quickly explain how we do that in about 20 seconds of your time?\"\n\n"
            f"Rules:\n"
            f"- NO formal greetings or sign-offs\n"
            f"- NO \"I hope this email finds you well\" type phrases\n"
            f"- Be specific about their industry/niche\n"
            f"- Keep it conversational like a text message\n"
            f"- End with the permission question"
        )

        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write extremely concise, casual B2B outreach messages. "
                        "No fluff, no corporate speak."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=150,
        )
        return response.choices[0].message.content.strip()

    def _guess_industry(self, company_name: str, website: str) -> str:
        """Guess industry from company name or website."""
        company_lower = company_name.lower()
        if any(word in company_lower for word in ['tech', 'software', 'saas', 'digital']):
            return "SaaS/tech"
        if any(word in company_lower for word in ['marketing', 'agency', 'creative', 'media']):
            return "marketing agencies"
        if any(word in company_lower for word in ['construction', 'build', 'contractor']):
            return "construction"
        if any(word in company_lower for word in ['real estate', 'property', 'realty']):
            return "real estate"
        if any(word in company_lower for word in ['consulting', 'advisory', 'consultancy']):
            return "consulting firms"
        return "B2B companies"

    def summarize_conversation(self, conversations: List[Conversation]) -> str:
        """Summarize the entire conversation history."""
        if not conversations:
            return "No conversation history"

        conversation_text = ""
        for conv in conversations:
            direction = "Bot" if conv.direction == "outbound" else "Lead"
            conversation_text += f"{direction}: {conv.message_content}\n"

        prompt = (
            "Summarize this sales conversation in 2-3 sentences. Focus on:\n"
            "- Lead's level of interest\n"
            "- Current stage of the sales process\n"
            "- Next steps or what they're waiting for\n\n"
            f"Conversation:\n{conversation_text}\n\n"
            "Keep it concise and actionable."
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You summarize sales conversations concisely.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=150,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Error summarizing conversation: {str(e)}"

    def analyze_message_intent(self, message: str) -> Dict[str, Any]:
        """Analyze message to detect meeting requests or other intents."""
        prompt = (
            "Analyze this message and determine:\n"
            "1. Is the sender requesting a meeting/call? (yes/no)\n"
            "2. What is their sentiment? (positive/neutral/negative)\n"
            "3. Are they expressing interest in our services? (yes/no/unclear)\n"
            "4. What stage are they at? (permission_granted/confirmation_yes/scheduling/objection/general)\n"
            "5. Did they specify a meeting time? (yes/no)\n"
            "6. If yes, extract the time details (day, time, timezone if mentioned)\n"
            "7. Are they confirming a previously suggested time? (yes/no)\n\n"
            f"Message: \"{message}\"\n\n"
            "Respond in JSON format with keys: requesting_meeting, sentiment, expressing_interest, "
            "stage, specified_time, time_details, confirming_time"
        )

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You analyze sales conversations to understand intent, stage, and meeting scheduling details."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        return json.loads(response.choices[0].message.content)

    def parse_meeting_time(self, message: str, current_context: str = "") -> Dict[str, Any]:
        """Parse specific meeting time from message."""
        prompt = (
            "Extract meeting time information from this message:\n"
            f"Message: \"{message}\"\n"
            f"Context: \"{current_context}\"\n\n"
            "Return JSON with:\n"
            "- has_time: boolean (true if specific time mentioned)\n"
            "- day: string (e.g., \"Friday\", \"tomorrow\", \"next Tuesday\")\n"
            "- time: string (e.g., \"12:30pm\", \"2:00\", \"afternoon\")\n"
            "- relative_date: string (e.g., \"this Friday\", \"next week\")\n"
            "- confidence: number (0-1, how confident you are in the parsing)\n"
            "- parsed_datetime: string (if you can determine exact datetime, format: \"YYYY-MM-DD HH:MM\")\n\n"
            "Examples:\n"
            "- \"let's do Friday at 12:30pm\" → has_time: true, day: \"Friday\", time: \"12:30pm\"\n"
            "- \"tomorrow afternoon\" → has_time: true, day: \"tomorrow\", time: \"afternoon\"\n"
            "- \"sure\" (after time suggestion) → has_time: false, but could be confirmation"
        )

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert at parsing dates and times from natural language. "
                        "Be precise and conservative - only return has_time=true if you're confident about the time."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=150,
        )
        return json.loads(response.choices[0].message.content)

    def _determine_conversation_stage(
        self, history: List[Conversation], latest_message: str
    ) -> str:
        """Determine what stage of the sales conversation we're in."""
        latest_lower = latest_message.lower()

        # Check if they're providing specific meeting time
        if any(
            word in latest_lower
            for word in [
                'friday', 'monday', 'tuesday', 'wednesday', 'thursday',
                'saturday', 'sunday', 'tomorrow', 'am', 'pm', ':',
                'morning', 'afternoon', 'evening'
            ]
        ):
            return "time_specified"

        # Check if they're confirming a time we suggested
        if (
            any(word in latest_lower for word in ['sure', 'yes', 'sounds good', 'perfect', 'confirmed'])
            and len(history) > 0
        ):
            last_bot_message = next(
                (
                    conv.message_content
                    for conv in reversed(history)
                    if conv.direction == "outbound"
                ),
                "",
            )
            if any(
                word in last_bot_message.lower()
                for word in ['calendar', 'schedule', 'meeting', 'time']
            ):
                return "time_confirmed"

        # Check if they just gave permission
        if any(
            word in latest_lower
            for word in ['yes', 'sure', 'okay', 'go ahead', 'tell me more', '20 seconds']
        ):
            if len(history) <= 2:
                return "permission_granted"
            elif any(
                'does that make sense' in conv.message_content.lower()
                for conv in history[-2:]
            ):
                return "confirmation_yes"

        # Check for objections
        if any(
            word in latest_lower
            for word in ['busy', 'not interested', 'no thanks', 'already have', 'not now']
        ):
            return "objection"

        # Check if they're asking about scheduling
        if any(
            word in latest_lower
            for word in ['calendar', 'schedule', 'when', 'meeting', 'call']
        ):
            return "scheduling"

        return "general"

    def generate_reply(
        self, lead: Lead, conversations: List[Conversation], message: str
    ) -> str:
        """Generate a contextual reply based on conversation history."""
        try:
            conversation_history = []
            for conv in conversations[-10:]:
                role = "assistant" if conv.direction == "outbound" else "user"
                conversation_history.append(
                    {"role": role, "content": conv.message_content}
                )
            conversation_history.append({"role": "user", "content": message})

            system_prompt = (
                f"You are a sales representative following up with {lead.first_name} "
                f"from {lead.company_name}.\n\n"
                "Based on the conversation history, generate an appropriate response that:\n"
                "1. Acknowledges what they just said\n"
                "2. Moves the conversation forward\n"
                "3. If they mentioned a specific time, confirm it and suggest creating a calendar invite\n"
                "4. Be concise and professional\n\n"
                "Current conversation context:\n"
                "- Lead has expressed interest\n"
                "- You're trying to schedule a meeting\n"
                "- Be specific about next steps"
            )

            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    *conversation_history,
                ],
                temperature=0.7,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            # If you have a logger, use it here
            # self.logger.error(f"Error generating reply: {str(e)}")
            return (
                "Thanks for your response! Let me check my calendar and get back to you with some specific times."
            )

    def ask_for_availability(self, lead: Lead, context: str = "") -> str:
        """Generate a WhatsApp message asking for the lead's availability"""
        prompt = f"""
        Create a casual WhatsApp message asking {lead.first_name} for their availability for a meeting.
        
        The message should:
        1. Be casual and conversational (like a text message, not an email)
        2. Ask for 2-3 time slots that work for them
        3. Mention it's for a brief 30-minute call
        4. Be friendly but brief
        5. No formal email language like "Hope you're well" or "Best regards"
        6. Keep in mind you represent a business, so be polite and a bit formal
        
        Keep it under 40 words and sound like a WhatsApp message.
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You write casual WhatsApp messages. No formal email language. Keep it short and conversational."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=80
        )
        
        return response.choices[0].message.content.strip()

    # Update the parse_availability_slots method in GPTHandler.py
    def parse_availability_slots(self, message: str) -> List[Dict]:
        """Parse multiple time slots from lead's availability message"""
        current_year = datetime.datetime.now().year
        prompt = f"""
        Extract all time slots mentioned in this message:
        "{message}"
        
        Current year is {current_year}. If no year is specified, assume {current_year}.
        
        Return JSON with "slots" array, where each slot has:
        - day: string (e.g., "Monday", "20th June", "tomorrow")
        - time: string (e.g., "11am-1pm", "2:00 PM", "morning")
        - confidence: number (0-1)
        - parsed_datetime: string (YYYY-MM-DD HH:MM format, using {current_year} if no year specified)
        
        Example input: "20th June, 11am-1pm"
        Example output: {{"slots": [{{"day": "20th June", "time": "11am-1pm", "confidence": 0.9, "parsed_datetime": "{current_year}-06-20 11:00"}}]}}
        
        IMPORTANT: Always use {current_year} for the year unless explicitly specified otherwise.
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": f"Extract time slots from natural language. Always use {current_year} as the year unless specified otherwise. Return valid JSON with 'slots' array."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                max_tokens=400
            )
            
            result = json.loads(response.choices[0].message.content)
            slots = result.get('slots', [])
            
            # Add debug logging
            self.logger.info(f"Parsed {len(slots)} availability slots from: '{message}'")
            for i, slot in enumerate(slots):
                self.logger.info(f"  Slot {i+1}: {slot}")
            
            return slots
            
        except Exception as e:
            self.logger.error(f"Error parsing availability slots: {e}")
            return []