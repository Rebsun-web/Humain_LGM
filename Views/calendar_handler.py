from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
import pickle
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from Configs.config import config


class CalendarHandler:
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self):
        self.creds = self._get_credentials()
        self.service = build('calendar', 'v3', credentials=self.creds)
    
    def _get_credentials(self):
        """Get Google Calendar credentials"""
        creds = None
        
        # Token file stores the user's access and refresh tokens
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        
        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    config.GOOGLE_CALENDAR_CREDENTIALS_PATH, self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        
        return creds
    
    def get_busy_times(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Get busy times from calendar"""
        try:
            # Get all events in the time range
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_date.isoformat() + 'Z',
                timeMax=end_date.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            busy_times = []
            for event in events:
                start = event.get('start', {})
                end = event.get('end', {})
                
                if 'dateTime' in start:
                    busy_times.append({
                        'start': datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00')),
                        'end': datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
                    })
            
            return busy_times
            
        except Exception as e:
            print(f"Error getting busy times: {e}")
            return []
    
    def get_available_slots(self, duration_minutes: int = 30, days_ahead: int = 3) -> List[Dict]:
        """Get available meeting slots"""
        slots = []
        current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Get busy times for the next N days
        end_date = current_date + timedelta(days=days_ahead)
        busy_times = self.get_busy_times(current_date, end_date)
        
        # Generate potential slots for each day
        for day_offset in range(days_ahead):
            date = current_date + timedelta(days=day_offset)
            
            # Skip weekends
            if date.weekday() >= 5:
                continue
            
            # Check each hour during business hours
            for hour in range(config.BUSINESS_START_HOUR, config.BUSINESS_END_HOUR):
                slot_start = date.replace(hour=hour, minute=0)
                slot_end = slot_start + timedelta(minutes=duration_minutes)
                
                # Check if slot conflicts with busy times
                is_available = True
                for busy in busy_times:
                    if (slot_start < busy['end'] and slot_end > busy['start']):
                        is_available = False
                        break
                
                if is_available:
                    slots.append({
                        'start': slot_start,
                        'end': slot_end,
                        'display': slot_start.strftime("%A, %B %d at %I:%M %p")
                    })
        
        return slots
    
    def create_meeting(
        self,
        summary: str,
        start_time: datetime,
        duration_minutes: int = 30,
        attendee_email: str = None,
        description: str = None
    ) -> Optional[str]:
        """Create a calendar event"""
        try:
            event = {
                'summary': summary,
                'description': description or '',
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': config.TIMEZONE,
                },
                'end': {
                    'dateTime': (start_time + timedelta(minutes=duration_minutes)).isoformat(),
                    'timeZone': config.TIMEZONE,
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},
                        {'method': 'popup', 'minutes': 10},
                    ],
                },
            }
            
            if attendee_email:
                event['attendees'] = [{'email': attendee_email}]
                event['conferenceData'] = {
                    'createRequest': {
                        'requestId': f"meeting_{start_time.timestamp()}",
                        'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                    }
                }
            
            event = self.service.events().insert(
                calendarId='primary',
                body=event,
                conferenceDataVersion=1,
                sendUpdates='all'
            ).execute()
            
            return event.get('id')
            
        except Exception as e:
            print(f"Error creating meeting: {e}")
            return None
