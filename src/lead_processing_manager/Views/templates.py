class Templates:
    """Quick templates based on the proven formula"""
    
    @staticmethod
    def get_initial_outreach(first_name: str, company_type: str, location: str = "Dubai"):
        """Get initial outreach template"""
        templates = [
            f"""Hi {first_name},

We partner with {company_type} in {location} who are prioritizing growth and 
guarantee to add £100k/month in new revenue over 6 months on a zero risk basis.

Would you be interested in a brief explanation of our approach?""",

            f"""Hi {first_name},

We specialize in helping {company_type} in {location} achieve £100k/month in 
predictable revenue within 6 months, with zero risk involved.

May I share our methodology with you?""",

            f"""Hi {first_name},

We work with {company_type} in {location} to deliver £100k/month in new revenue 
over 6 months - with no risk to your business.

Would you like to learn more about our approach?"""
        ]
        
        import random
        return random.choice(templates)
    
    @staticmethod
    def get_explanation():
        """Get the 3-step explanation"""
        return """We have a 3 step process:

1. Go-to-market strategy - we research your ideal customer and find the best markets to target
2. Sales development - we build a system that brings in qualified opportunities consistently 
3. Sales enablement - we give you our proven B2B process to close those opportunities

Does that make sense?"""
    
    @staticmethod
    def get_meeting_request(day1: str, day2: str, time1: str, time2: str):
        """Get meeting request template"""
        return f"""Cool - I'm looking to set up a time to chat next week, just to get introduced and aligned on this going forward.

How does your calendar look next week on {day1}/{day2} at {time1}/{time2}?"""
    
    @staticmethod
    def handle_common_objections(objection_type: str):
        """Quick responses to common objections"""
        responses = {
            "busy": "Totally understand you're busy. That's exactly why we handle everything for you. Quick 15 min call next week to see if it's a fit?",
            
            "not_interested": "No worries. Just curious - is it the timing or you're already hitting your growth targets?",
            
            "already_have": "Nice, who are you working with? We often complement existing efforts. Worth a quick chat to compare notes?",
            
            "no_budget": "That's why we work on a performance basis - you only pay from the new revenue we generate. Make sense to explore?",
        }
        
        return responses.get(objection_type, "Got it. If things change, I'm here. Have a great day!")
