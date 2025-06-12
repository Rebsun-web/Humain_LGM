import asyncio
from datetime import datetime
import pytz
from lead_processing_manager.Main.lead_processor import LeadProcessor
from lead_processing_manager.Views.excel_handler import ExcelHandler
from lead_processing_manager.Configs.config import config
from lead_processing_manager.Utils.logging_utils import setup_logger, log_function_call
from lead_processing_manager.Utils.db_utils import db_session, init_database

# Set up logging
logger = setup_logger(__name__)

@log_function_call(logger)
async def process_leads():
    """Main function to process leads"""
    try:
        logger.info("Starting lead processing system...")
        
        # Initialize database
        init_database()
        
        # Initialize handlers
        logger.debug("Initializing handlers...")
        excel_handler = ExcelHandler()
        lead_processor = LeadProcessor()
        
        # Check business hours
        dubai_tz = pytz.timezone(config.TIMEZONE)
        current_hour = datetime.now(dubai_tz).hour
        logger.debug(f"Current hour in {config.TIMEZONE}: {current_hour}")
        
        if not (config.BUSINESS_START_HOUR <= current_hour <= config.BUSINESS_END_HOUR):
            logger.info(
                f"Outside business hours ({config.BUSINESS_START_HOUR}:00 - "
                f"{config.BUSINESS_END_HOUR}:00 {config.TIMEZONE}). "
                "Skipping processing."
            )
            return
        
        # Process new leads from Excel
        logger.info("Checking for new leads in Excel...")
        new_leads_data = excel_handler.check_for_new_leads()
        
        if new_leads_data:
            logger.info(f"Found {len(new_leads_data)} new leads")
            with db_session() as db:
                # Add leads to database and get back the new leads
                new_leads = excel_handler.add_leads_to_database(new_leads_data, db)
                db.commit()  # Commit to ensure all leads are saved
                
                # Process each lead within the same session
                for lead in new_leads:
                    try:
                        logger.debug(
                            f"Processing lead: {lead.first_name} {lead.last_name}"
                        )
                        await lead_processor.process_new_lead(lead)
                        db.refresh(lead)  # Refresh the lead object after processing
                    except Exception as e:
                        logger.error(
                            f"Error processing lead {lead.id}: {str(e)}",
                            exc_info=True
                        )
                        db.rollback()  # Rollback on error
                    else:
                        db.commit()  # Commit successful processing
        else:
            logger.info("No new leads found")
        
        # Process follow-ups
        logger.info("Processing follow-ups...")
        try:
            await lead_processor.process_follow_ups()
        except Exception as e:
            logger.error(
                "Error processing follow-ups",
                exc_info=True
            )
        
        logger.info("Lead processing completed successfully")
        
    except Exception as e:
        logger.error(
            "Fatal error in lead processing",
            exc_info=True
        )
        raise

if __name__ == "__main__":
    try:
        # Run the async function
        asyncio.run(process_leads())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(
            "Fatal error in main process",
            exc_info=True
        )
