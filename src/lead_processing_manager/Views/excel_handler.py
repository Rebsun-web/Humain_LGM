import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional
from lead_processing_manager.Models.models import Lead, LeadStatus
from lead_processing_manager.Utils.logging_utils import setup_logger, log_function_call
from lead_processing_manager.Configs.config import config
from sqlalchemy import select
from sqlalchemy.orm import Session


class ExcelHandler:
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.leads_file = config.LEADS_FILE
        self.logger.info(f"ExcelHandler initialized with file: {self.leads_file}")
    
    @log_function_call(setup_logger(__name__))
    def check_for_new_leads(self) -> List[Dict]:
        """Check Excel file for new leads"""
        try:
            self.logger.debug(f"Reading leads from {self.leads_file}")
            # Read phone numbers as strings
            df = pd.read_excel(
                self.leads_file,
                dtype={'phone_number': str}
            )
            
            # Convert DataFrame to list of dictionaries
            leads_data = df.to_dict('records')
            
            # Ensure phone numbers are strings
            for lead in leads_data:
                if 'phone_number' in lead and lead['phone_number'] is not None:
                    lead['phone_number'] = str(lead['phone_number'])
            
            self.logger.info(f"Found {len(leads_data)} leads in Excel")
            
            return leads_data
            
        except Exception as e:
            self.logger.error(
                f"Error reading leads from Excel: {str(e)}",
                exc_info=True
            )
            return []
    
    @log_function_call(setup_logger(__name__))
    def add_leads_to_database(self, leads_data: List[Dict], db: Session) -> List[Lead]:
        """Add new leads to database, update existing ones"""
        new_leads = []
        try:
            for lead_data in leads_data:
                try:
                    # Check if lead already exists by email
                    existing_lead = db.scalar(
                        select(Lead).where(Lead.email == lead_data['email'])
                    )
                    
                    if existing_lead:
                        self.logger.debug(
                            f"Found existing lead: {lead_data['email']}"
                        )
                        # If lead exists but is in NEW status, treat it as new
                        if existing_lead.status == LeadStatus.NEW:
                            self.logger.info(
                                f"Lead {lead_data['email']} is in NEW status, "
                                f"will process again"
                            )
                            new_leads.append(existing_lead)
                        else:
                            self._update_lead(existing_lead, lead_data)
                    else:
                        self.logger.debug(
                            f"Creating new lead: {lead_data['email']}"
                        )
                        new_lead = self._create_lead(lead_data)
                        db.add(new_lead)
                        new_leads.append(new_lead)
                        
                except Exception as e:
                    self.logger.error(
                        f"Error processing lead {lead_data.get('email')}: "
                        f"{str(e)}",
                        exc_info=True
                    )
                    continue
            
            self.logger.info(
                f"Added {len(new_leads)} new leads to database"
            )
                
        except Exception as e:
            self.logger.error(
                "Error in database transaction",
                exc_info=True
            )
            
        return new_leads
    
    def _create_lead(self, lead_data: Dict) -> Lead:
        """Create a new Lead object from dictionary data"""
        now = datetime.utcnow()
        return Lead(
            first_name=lead_data.get('first_name', ''),
            last_name=lead_data.get('last_name', ''),
            company_name=lead_data.get('company_name', ''),
            company_website=lead_data.get('company_website', ''),
            phone_number=lead_data.get('phone_number', ''),
            linkedin_url=lead_data.get('linkedin_url', ''),
            email=lead_data.get('email', ''),
            email_verified=lead_data.get('email_verified', False),
            created_at=now,
            updated_at=now,
            custom_data=lead_data.get('custom_data', {})
        )
    
    def _update_lead(self, lead: Lead, new_data: Dict) -> None:
        """Update an existing lead with new data"""
        lead.first_name = new_data.get('first_name', lead.first_name)
        lead.last_name = new_data.get('last_name', lead.last_name)
        lead.company_name = new_data.get('company_name', lead.company_name)
        lead.company_website = new_data.get(
            'company_website',
            lead.company_website
        )
        lead.phone_number = new_data.get('phone_number', lead.phone_number)
        lead.linkedin_url = new_data.get('linkedin_url', lead.linkedin_url)
        lead.email_verified = new_data.get(
            'email_verified',
            lead.email_verified
        )
        lead.updated_at = datetime.utcnow()
        
        if new_data.get('custom_data'):
            lead.custom_data.update(new_data['custom_data'])
