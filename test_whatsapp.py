import asyncio
from lead_processing_manager.Views.whatsapp_handler import WhatsAppHandler
from lead_processing_manager.Models.models import Lead
import os
from dotenv import load_dotenv

# Force reload environment variables
load_dotenv(override=True)

print("DEBUG: Environment variables:")
print(f"WHATSAPP_API_TOKEN: {os.getenv('WHATSAPP_API_TOKEN', 'NOT FOUND')[:20]}...")

async def test_whatsapp():
    # Initialize the WhatsApp handler
    whatsapp = WhatsAppHandler()
    
    # Create a test lead
    test_lead = Lead(
        first_name="Nikita",
        last_name="Voronkin",
        phone_number="+31 6 53470562",
        email="voronkinikita@gmail.com",
        company_name="ASML"
    )
    
    # Test message
    message = "👋 Hello! This is a test message from your Lead Processing Manager. If you receive this, the WhatsApp integration is working correctly!"
    
    # Format phone number for WhatsApp API (no plus sign, just numbers)
    phone = ''.join(filter(str.isdigit, test_lead.phone_number))
    
    print(f"\nSending test message to: {phone}")
    print(f"Using WhatsApp Phone Number ID: {whatsapp.phone_number_id}")
    print(f"API URL: {whatsapp.api_url}")
    print(f"Test mode: {whatsapp.test_mode}")
    
    # Send the message
    success = whatsapp.send_message(phone, message)
    
    if success:
        print("\n✅ Message sent successfully!")
    else:
        print("\n❌ Failed to send message")

if __name__ == "__main__":
    asyncio.run(test_whatsapp())
