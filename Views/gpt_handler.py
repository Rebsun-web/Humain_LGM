import openai
import json
from typing import Dict, List
from config import config
from models import Lead, Conversation

openai.api_key = config.OPENAI_API_KEY


class GPTHandler:
    def __init__(self):
        self.client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    
    def generate_initial_outreach(self, lead: Lead) -> str:
        """Generate personalized initial outreach message"""
        prompt = f"""
        Create a personalized, professional outreach message for a B2B lead generation service.
        
        Lead Information:
        - Name: {lead.first_name} {lead.last_name}
        - Company: {lead.company_name}
        - Website: {lead.company_website}
        
        Instructions:
        1. Keep it concise (max 150 words)
        2. Reference something specific about their company (use the website info)
        3. Briefly mention how our lead generation services could help them
        4. End with a soft call-to-action
        5. Be professional but conversational
        6. Don't be too salesy
        
        Write the message:
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a professional B2B sales representative specializing in lead generation services."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=300
        )
        
        return response.choices[0].message.content.strip()
    
    def generate_reply(self, lead: Lead, conversation_history: List[Conversation], new_message: str) -> str:
        """Generate contextual reply based on conversation history"""
        
        # Build conversation context
        context = f"""
        Lead Information:
        - Name: {lead.first_name} {lead.last_name}
        - Company: {lead.company_name}
        - Status: {lead.status.value}
        - Summary: {lead.conversation_summary or 'No previous summary'}
        
        Conversation History:
        """
        
        for conv in conversation_history[-5:]:  # Last 5 messages for context
            direction = "Us" if conv.direction == "outbound" else "Lead"
            context += f"\n{direction}: {conv.message_content}"
        
        context += f"\nLead: {new_message}"
        
        prompt = f"""
        {context}
        
        Instructions:
        1. Respond appropriately to the lead's message
        2. If they show interest, guide them towards scheduling a meeting
        3. If they ask questions, answer them clearly
        4. Maintain a professional, helpful tone
        5. Keep responses concise and focused
        6. If they want to schedule a meeting, acknowledge it positively
        
        Write your response:
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a professional B2B sales representative. You're helpful, knowledgeable, and focused on understanding the lead's needs."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=250
        )
        
        return response.choices[0].message.content.strip()
    
    def analyze_message_intent(self, message: str) -> Dict[str, any]:
        """Analyze message to detect meeting requests or other intents"""
        prompt = f"""
        Analyze this message and determine:
        1. Is the sender requesting a meeting/call? (yes/no)
        2. What is their sentiment? (positive/neutral/negative)
        3. Are they expressing interest in our services? (yes/no/unclear)
        4. Brief summary of their intent (one sentence)
        
        Message: "{message}"
        
        Respond in JSON format:
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are analyzing business communication to understand intent."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        return json.loads(response.choices[0].message.content)
    
    def summarize_conversation(self, conversation_history: List[Conversation]) -> str:
        """Create a summary of the conversation for quick reference"""
        if not conversation_history:
            return "No conversation yet"
        
        context = "Conversation history:\n"
        for conv in conversation_history:
            direction = "Us" if conv.direction == "outbound" else "Lead"
            context += f"{direction}: {conv.message_content}\n"
        
        prompt = f"""
        {context}
        
        Create a brief summary (4-5 sentences) of this conversation, focusing on:
        1. The lead's main interests or concerns
        2. Their level of engagement
        3. Any specific requirements or next steps mentioned
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You create concise business conversation summaries."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=150
        )
        
        return response.choices[0].message.content.strip()