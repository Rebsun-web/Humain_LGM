import asyncio
import time
import os
import sys
import signal
import schedule
from datetime import datetime
from threading import Thread
from flask import request
from lead_processing_manager.Views.excel_handler import ExcelHandler
from lead_processing_manager.Main.lead_processor import LeadProcessor
from lead_processing_manager.Views.telegram_bot import TelegramBot
from lead_processing_manager.Models.models import (
    Lead, LeadStatus, SessionLocal
)
from lead_processing_manager.Configs.config import config
from lead_processing_manager.Views.webhook_manager import WebhookManager
from lead_processing_manager.Utils.db_utils import db_session
from lead_processing_manager.Utils.logging_utils import setup_logger


class LeadAutomationSystem:
    def __init__(self):
        self.excel_handler = ExcelHandler()
        self.lead_processor = LeadProcessor()
        self.telegram_bot = TelegramBot()
        self.webhook_manager = WebhookManager(self.lead_processor)
        self.is_running = True
        self.logger = setup_logger(__name__)
        self.cleanup_telegram_bot()  # Clean up any existing bot instances
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
    
    def handle_shutdown(self, signum, frame):
        """Handle graceful shutdown"""
        print("\nShutting down Lead Automation System...")
        self.is_running = False
        
        # Clean up Telegram bot
        if self.telegram_bot and self.telegram_bot._application:
            try:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(self.telegram_bot.cleanup())
            except Exception as e:
                print(f"Error cleaning up Telegram bot: {e}")
        
        # Clean up WhatsApp handler
        if hasattr(self.lead_processor, 'whatsapp_handler'):
            try:
                # Stop the Flask server
                func = request.environ.get('werkzeug.server.shutdown')
                if func is not None:
                    func()
            except Exception as e:
                print(f"Error cleaning up WhatsApp handler: {e}")
        
        sys.exit(0)
    
    def cleanup_telegram_bot(self):
        """Clean up any existing Telegram bot instances"""
        try:
            # Find any Python processes running Telegram bot
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] == 'python' and proc.pid != os.getpid():
                        cmdline = proc.info.get('cmdline', [])
                        if any('telegram' in cmd.lower() for cmd in cmdline):
                            os.kill(proc.pid, signal.SIGTERM)
                            print(
                                f"Terminated existing Telegram bot process: {proc.pid}"
                            )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            print(f"Error cleaning up Telegram bot: {e}")
    
    async def check_new_leads(self):
        """Check for new leads in Excel file"""
        print(f"[{datetime.now()}] Checking for new leads...")
        
        # Check Excel for new leads
        new_leads_data = self.excel_handler.check_for_new_leads()
        
        if new_leads_data:
            print(f"Found {len(new_leads_data)} new leads")
            db = SessionLocal()
            try:
                new_leads = self.excel_handler.add_leads_to_database(new_leads_data, db)
            finally:
                db.close()
            # Process each new lead
            for lead in new_leads:
                await self.lead_processor.process_new_lead(lead)
    
    async def process_existing_leads(self):
        """Process existing leads"""
        print(f"[{datetime.now()}] Processing existing leads...")
        # Process follow-ups
        await self.lead_processor.process_follow_ups()
    
    async def daily_summary(self):
        """Send daily summary to managers"""
        db = SessionLocal()
        try:
            # Get lead statistics
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
            # Get WhatsApp usage stats
            whatsapp_stats = self.lead_processor.whatsapp_handler.get_usage_stats()
            summary = (
                f"\n📊 <b>Daily Lead Summary</b>\n\n"
                f"<b>📈 Lead Statistics:</b>\n"
                f"- Total Leads: {total_leads}\n"
                f"- New Today: {new_leads}\n"
                f"- Interested: {interested_leads}\n"
                f"- Meetings Scheduled: {scheduled_meetings}\n\n"
                f"<b>📱 WhatsApp Usage:</b>\n"
                f"- Sent Today: {whatsapp_stats['daily_count']}/{whatsapp_stats['daily_limit']}\n"
                f"- Remaining: {whatsapp_stats['daily_remaining']}\n"
                f"- Total Messages: {whatsapp_stats['total_sent']}\n\n"
                f"System is running smoothly. All leads are being processed automatically."
            )
            await self.telegram_bot.send_message(summary)
        except Exception as e:
            print(f"Error generating daily summary: {e}")
        finally:
            db.close()
    
    def run_telegram_bot(self):
        """Run Telegram bot in separate thread"""
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Start the bot
        application = self.telegram_bot.setup_bot()
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        loop.run_until_complete(application.updater.start_polling())
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(application.stop())
            loop.close()
    
    async def main_loop(self):
        """Main processing loop"""
        while self.is_running:
            try:
                # Check for new leads every hour
                await self.check_new_leads()

                # Process existing leads every 15 minutes
                await self.process_existing_leads()
                
                # Process WhatsApp outreach (if enabled and handler exists)
                if config.WHATSAPP_ENABLED and self.lead_processor.whatsapp_handler:
                    await self.lead_processor.process_bulk_whatsapp_outreach()
                
                # Wait 15 minutes before next cycle
                await asyncio.sleep(900)  # 15 minutes
            except Exception as e:
                print(f"Error in main loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error

    def start_server(self, port: int = None):
        """Start the webhook server"""
        port = port or config.WHATSAPP_WEBHOOK_PORT or 8090
        
        def run_server():
            try:
                self.logger.info(f"Starting webhook server on port {port}")
                self.webhook_manager.app.run(host='0.0.0.0', port=port, debug=False)
            except OSError as e:
                if "Address already in use" in str(e):
                    # Try alternative ports
                    for alt_port in range(port + 1, port + 10):
                        try:
                            self.logger.info(f"Port {port} in use, trying port {alt_port}")
                            self.app.run(host='0.0.0.0', port=alt_port, debug=False)
                            break
                        except OSError:
                            continue
                else:
                    self.logger.error(f"Failed to start webhook server: {e}")
            except Exception as e:
                self.logger.error(f"Failed to start webhook server: {e}")

        Thread(target=run_server, daemon=True).start()
    
    def start(self):
        """Start the lead automation system"""
        print("Starting Lead Automation System...")
        
        # Start webhook server
        self.start_server()
        
        # Start Telegram bot in separate thread
        telegram_thread = Thread(target=self.run_telegram_bot)
        telegram_thread.daemon = True
        telegram_thread.start()
        
        # Schedule daily summary at 6 PM
        schedule.every().day.at("18:00").do(
            lambda: asyncio.create_task(self.telegram_bot.send_daily_lead_summary())
        )
        
        # Schedule weekly summary on Fridays at 5 PM
        schedule.every().friday.at("17:00").do(
            lambda: asyncio.create_task(self.send_weekly_summary())
        )
        
        # Start scheduler in separate thread
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        scheduler_thread = Thread(target=run_scheduler)
        scheduler_thread.daemon = True
        scheduler_thread.start()
        
        # Run main loop
        try:
            asyncio.run(self.main_loop())
        except KeyboardInterrupt:
            print("\nShutting down Lead Automation System...")
            self.is_running = False

    async def send_weekly_summary(self):
        """Send weekly summary to managers"""
        try:
            week_start = datetime.now().replace(hour=0, minute=0, second=0) - timedelta(days=7)
            
            with db_session() as db:
                # Weekly stats
                total_leads = db.query(Lead).filter(Lead.created_at >= week_start).count()
                contacted_leads = db.query(Lead).filter(
                    Lead.last_contact_date >= week_start,
                    Lead.status.in_([LeadStatus.CONTACTED, LeadStatus.FOLLOW_UP])
                ).count()
                responded_leads = db.query(Lead).filter(
                    Lead.status.in_([
                        LeadStatus.RESPONDED, 
                        LeadStatus.INTERESTED, 
                        LeadStatus.MEETING_REQUESTED
                    ])
                ).count()
                meetings_scheduled = db.query(Lead).filter(
                    Lead.status.in_([
                        LeadStatus.MEETING_SCHEDULED, 
                        LeadStatus.MEETING_CONFIRMED
                    ])
                ).count()
                
                summary = f"""
                    📈 <b>Weekly Summary</b>

                    <b>This Week:</b>
                    - New leads: {total_leads}
                    - Leads contacted: {contacted_leads}
                    - Leads responded: {responded_leads}
                    - Meetings scheduled: {meetings_scheduled}

                    <b>Conversion Rate:</b>
                    - Response rate: {(responded_leads/contacted_leads*100):.1f}% 
                    {'0.0%' if contacted_leads == 0 else f'{(responded_leads/contacted_leads*100):.1f}%'}
                    - Meeting rate: {(meetings_scheduled/responded_leads*100):.1f}% 
                    {'0.0%' if responded_leads == 0 else f'{(meetings_scheduled/responded_leads*100):.1f}%'}
                """
                await self.telegram_bot.send_message(summary)
                
        except Exception as e:
            print(f"Error generating weekly summary: {e}")


if __name__ == "__main__":
    system = LeadAutomationSystem()
    system.start()
