import pandas as pd
from typing import List, Dict
from config import config
from models import Lead, SessionLocal


class ExcelHandler:
    def __init__(self, file_path: str = None):
        self.file_path = file_path or config.EXCEL_FILE_PATH
        self.processed_emails = self._load_processed_emails()
    
    def _load_processed_emails(self) -> set:
        """Load already processed email addresses from database"""
        db = SessionLocal()
        existing_leads = db.query(Lead.email).all()
        db.close()
        return {lead.email for lead in existing_leads}
    
    def check_for_new_leads(self) -> List[Dict]:
        """Check Excel file for new leads"""
        try:
            # Read Excel file
            df = pd.read_excel(self.file_path)
            
            # Expected columns
            expected_columns = [
                'first_name', 'last_name', 'company_name', 
                'company_website', 'phone_number', 'linkedin_url',
                'email', 'email_verified'
            ]
            
            # Normalize column names
            df.columns = df.columns.str.lower().str.replace(' ', '_')
            
            new_leads = []
            
            for _, row in df.iterrows():
                email = row.get('email')
                
                # Skip if email is empty or already processed
                if pd.isna(email) or email in self.processed_emails:
                    continue
                
                # Create lead data
                lead_data = {
                    'first_name': row.get('first_name', ''),
                    'last_name': row.get('last_name', ''),
                    'company_name': row.get('company_name', ''),
                    'company_website': row.get('company_website', ''),
                    'phone_number': str(row.get('phone_number', '')) if not pd.isna(row.get('phone_number')) else None,
                    'linkedin_url': row.get('linkedin_url', ''),
                    'email': email,
                    'email_verified': bool(row.get('email_verified', False))
                }
                
                new_leads.append(lead_data)
                self.processed_emails.add(email)
            
            return new_leads
            
        except Exception as e:
            print(f"Error reading Excel file: {e}")
            return []
    
    def add_leads_to_database(self, leads_data: List[Dict]) -> List[Lead]:
        """Add new leads to database"""
        db = SessionLocal()
        new_leads = []
        
        for lead_data in leads_data:
            try:
                lead = Lead(**lead_data)
                db.add(lead)
                db.commit()
                db.refresh(lead)
                new_leads.append(lead)
            except Exception as e:
                print(f"Error adding lead {lead_data.get('email')}: {e}")
                db.rollback()
        
        db.close()
        return new_leads
