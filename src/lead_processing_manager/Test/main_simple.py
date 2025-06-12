import asyncio
from datetime import datetime
from lead_processing_manager.Views.excel_handler import ExcelHandler
from lead_processing_manager.Main.lead_processor import LeadProcessor
from lead_processing_manager.Models.models import Lead
from lead_processing_manager.Utils.db_utils import db_session


async def test_run():
    """Test run to process one lead"""
    excel_handler = ExcelHandler()
    lead_processor = LeadProcessor()
    
    # Check for new leads
    print(f"[{datetime.now()}] Checking for new leads...")
    new_leads_data = excel_handler.check_for_new_leads()
    
    if new_leads_data:
        print(f"Found {len(new_leads_data)} new leads")
        with db_session() as db:
            new_leads = excel_handler.add_leads_to_database(new_leads_data, db)
            
            # Process first lead only for testing
            if new_leads:
                lead = new_leads[0]
                print(f"Processing lead: {lead.first_name} {lead.last_name}")
                await lead_processor.process_new_lead(lead)
                print("✅ Test complete! Check your email and Telegram")
    else:
        print("No new leads found")
        
        # Show existing leads
        with db_session() as db:
            existing = db.query(Lead).count()
            print(f"Total leads in database: {existing}")

if __name__ == "__main__":
    asyncio.run(test_run())
