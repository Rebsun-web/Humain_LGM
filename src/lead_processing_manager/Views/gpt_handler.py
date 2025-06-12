import openai
from typing import Dict, List
from lead_processing_manager.Configs.config import config
from lead_processing_manager.Models.models import Lead, Conversation


openai.api_key = config.OPENAI_API_KEY


class GPTHandler:
    def __init__(self):
        self.client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    
    def generate_initial_outreach(self, lead: Lead) -> str:
        """Generate personalized initial outreach using the proven formula"""
        
        # Extract industry from company website or name
        industry = self._guess_industry(lead.company_name, lead.company_website)
        
        prompt = f"""
        Create a SHORT, CASUAL cold email using this exact formula:
        
        1. {{Opener}} - Direct, no pleasantries
        2. {{Value statement}} - Specific to their niche
        3. {{Permission to explain}} - Ask for 20-30 seconds
        4. Keep TOTAL email under 100 words
        
        Lead info:
        - Name: {lead.first_name}
        - Company: {lead.company_name}
        - Industry: {industry}
        - Location: Dubai/UAE
        
        Use this structure:
        "Hi {lead.first_name},
        
        We partner with [specific niche] companies in [location] who are prioritizing growth and guarantee to add £100k/month in new revenue over 6 months on a zero risk basis.
        
        Can I quickly explain how we do that in about 20 seconds of your time?"
        
        Rules:
        - NO formal greetings or sign-offs
        - NO "I hope this email finds you well" type phrases
        - Be specific about their industry/niche
        - Keep it conversational like a text message
        - End with the permission question
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You write extremely concise, casual B2B outreach messages. No fluff, no corporate speak."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=150
        )
        
        return response.choices[0].message.content.strip()
    
    def generate_reply(self, lead: Lead, conversation_history: List[Conversation], new_message: str) -> str:
        """Generate contextual reply based on conversation history"""
        
        # Analyze what stage we're at
        stage = self._determine_conversation_stage(conversation_history, new_message)
        
        # Build conversation context
        context = f"""
        Lead: {lead.first_name} from {lead.company_name}
        Their last message: "{new_message}"
        
        Conversation stage: {stage}
        """
        
        if stage == "permission_granted":
            prompt = f"""
            {context}
            
            They agreed to hear more. Now give the 3-step explanation (keep it under 100 words):
            1. Go-to-market strategy (finding best markets)
            2. Sales development (reliable flow of opportunities)
            3. Sales enablement (proven B2B process)
            
            End with: "Does that make sense?"
            
            Keep it conversational, like you're texting.
            """
        
        elif stage == "confirmation_yes":
            prompt = f"""
            {context}
            
            They said it makes sense. Now book the meeting:
            "Cool - I'm looking to set up a time to chat next week, just to get introduced and aligned on this going forward - how does your calendar look next week on [day]/[day] at [time]/[time]?"
            
            Be specific with actual days/times.
            """
        
        elif stage == "objection":
            prompt = f"""
            {context}
            
            Handle their objection in under 50 words. Be direct, address their concern, then redirect to booking a call.
            No corporate speak, keep it casual.
            """
        
        else:  # general response
            prompt = f"""
            {context}
            
            Reply in under 50 words. If they show ANY interest, immediately try to book a meeting.
            If they ask questions, answer briefly then pivot to scheduling.
            
            Always be closing for the meeting.
            """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You write like you're sending a quick text message. Super casual, no corporate language, always pushing for the meeting."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=120
        )
        
        return response.choices[0].message.content.strip()
    
    def _determine_conversation_stage(self, history: List[Conversation], latest_message: str) -> str:
        """Determine what stage of the sales conversation we're in"""
        
        latest_lower = latest_message.lower()
        
        # Check if they just gave permission
        if any(word in latest_lower for word in ['yes', 'sure', 'okay', 'go ahead', 'tell me more', '20 seconds']):
            # Check if this is after our initial ask
            if len(history) <= 2:
                return "permission_granted"
            # Check if this is after our explanation
            elif any('does that make sense' in conv.message_content.lower() for conv in history[-2:]):
                return "confirmation_yes"
        
        # Check for objections
        if any(word in latest_lower for word in ['busy', 'not interested', 'no thanks', 'already have', 'not now']):
            return "objection"
        
        # Check if they're asking about scheduling
        if any(word in latest_lower for word in ['calendar', 'schedule', 'when', 'meeting', 'call']):
            return "scheduling"
        
        return "general"
    
    def _guess_industry(self, company_name: str, website: str) -> str:
        """Guess industry from company name or website"""
        company_lower = company_name.lower()
        
        # Common industry keywords
        if any(word in company_lower for word in ['tech', 'software', 'saas', 'digital']):
            return "SaaS/tech"
        elif any(word in company_lower for word in ['marketing', 'agency', 'creative', 'media']):
            return "marketing agencies"
        elif any(word in company_lower for word in ['construction', 'build', 'contractor']):
            return "construction"
        elif any(word in company_lower for word in ['real estate', 'property', 'realty']):
            return "real estate"
        elif any(word in company_lower for word in ['consulting', 'advisory', 'consultancy']):
            return "consulting firms"
        else:
            return "B2B companies"
    
    def analyze_message_intent(self, message: str) -> Dict[str, any]:
        """Analyze message to detect meeting requests or other intents"""
        prompt = f"""
        Analyze this message and determine:
        1. Is the sender requesting a meeting/call? (yes/no)
        2. What is their sentiment? (positive/neutral/negative)
        3. Are they expressing interest in our services? (yes/no/unclear)
        4. What stage are they at? (permission_granted/confirmation_yes/scheduling/objection/general)
        
        Message: "{message}"
        
        Respond in JSON format.
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You analyze sales conversations to understand intent and stage."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        import json
        return json.loads(response.choices[0].message.content)