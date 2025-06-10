import asyncio
import schedule
import time
from datetime import datetime
import threading
from excel_handler import ExcelHandler
from lead_processor import LeadProcessor
from telegram_bot import TelegramBot
from models import Lead, LeadStatus, SessionLocal


class LeadAutomationSystem:
    def __init__(self):
        self.excel_handler = ExcelHandler()
        self.lead_processor = LeadProcessor()
        self.telegram_bot = TelegramBot()
        self.is_running = True
    
    async def check_new_leads(self):
        """Check for new leads in Excel file"""
        print(f"[{datetime.now()}] Checking for new leads...")
        
        # Check Excel for new leads
        new_leads_data = self.excel_handler.check_for_new_leads()
        
        if new_leads_data:
            print(f"Found {len(new_leads_data)} new leads")
            
            # Add to database
            new_leads = self.excel_handler.add_leads_to_database(new_leads_data)
            
            # Process each new lead
            for lead in new_leads:
                await self.lead_processor.process_new_lead(lead)
    
    async def process_existing_leads(self):
        """Process all existing leads"""
        print(f"[{datetime.now()}] Processing existing leads...")
        
        # Check for new responses
        await self.lead_processor.check_and_process_responses()
        
        # Process follow-ups
        await self.lead_processor.process_follow_ups()
    
    async def daily_summary(self):
        """Send daily summary to managers"""
        db = SessionLocal()
        
        try:
            # Get statistics
            total_leads = db.query(Lead).count()
            new_leads = db.query(Lead).filter(
                Lead.created_at >= datetime.now().replace(hour=0, minute=0, second=0)
            ).count()
            interested_leads = db.query(Lead).filter(
                Lead.status.in_([LeadStatus.INTERESTED, LeadStatus.MEETING_REQUESTED])
            ).count()
            scheduled_meetings = db.query(Lead).filter(
                Lead.status == LeadStatus.MEETING_SCHEDULED
            ).count()
            
            summary = f"""
📊 <b>Daily Lead Summary</b>

<b>Total Leads:</b> {total_leads}
<b>New Today:</b> {new_leads}
<b>Interested:</b> {interested_leads}
<b>Meetings Scheduled:</b> {scheduled_meetings}

System is running smoothly. All leads are being processed automatically.
            """
            
            await self.telegram_bot.send_message(summary)
            
        except Exception as e:
            print(f"Error generating daily summary: {e}")
        finally:
            db.close()
    
    def run_telegram_bot(self):
        """Run Telegram bot in separate thread"""
        self.telegram_bot.start_bot()
    
    async def main_loop(self):
        """Main processing loop"""
        while self.is_running:
            try:
                # Check for new leads every hour
                await self.check_new_leads()
                
                # Process existing leads every 15 minutes
                await self.process_existing_leads()
                
                # Wait 15 minutes before next cycle
                await asyncio.sleep(900)  # 15 minutes
                
            except Exception as e:
                print(f"Error in main loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error
    
    def start(self):
        """Start the lead automation system"""
        print("Starting Lead Automation System...")
        
        # Start Telegram bot in separate thread
        telegram_thread = threading.Thread(target=self.run_telegram_bot)
        telegram_thread.daemon = True
        telegram_thread.start()
        
        # Schedule daily summary
        schedule.every().day.at("09:00").do(
            lambda: asyncio.create_task(self.daily_summary())
        )
        
        # Start scheduler in separate thread
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        
        scheduler_thread = threading.Thread(target=run_scheduler)
        scheduler_thread.daemon = True
        scheduler_thread.start()
        
        # Run main loop
        try:
            asyncio.run(self.main_loop())
        except KeyboardInterrupt:
            print("\nShutting down Lead Automation System...")
            self.is_running = False


if __name__ == "__main__":
    system = LeadAutomationSystem()
    system.start()
