# Calendar_Handler.py
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
import pickle
import pytz
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from lead_processing_manager.Configs.config import config


class CalendarHandler:
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    OAUTH_PORT = 8095  # Changed port to avoid conflicts
    
    def __init__(self):
        self.creds = self._get_credentials()
        self.service = build('calendar', 'v3', credentials=self.creds)
        self.timezone = pytz.timezone(config.TIMEZONE if hasattr(config, 'TIMEZONE') else 'UTC')
    
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
                creds = flow.run_local_server(
                    port=self.OAUTH_PORT,
                    success_message='The authentication flow has completed. You may close this window.',
                    authorization_prompt_message='Please visit this URL to authorize this application: {url}'
                )
            
            # Save the credentials for the next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        
        return creds
    
    def get_busy_times(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Get busy times from calendar - FIXED VERSION"""
        try:
            # Make sure dates are timezone-aware
            if start_date.tzinfo is None:
                start_date = self.timezone.localize(start_date)
            if end_date.tzinfo is None:
                end_date = self.timezone.localize(end_date)
            
            # Convert to UTC for API call
            start_utc = start_date.astimezone(pytz.UTC)
            end_utc = end_date.astimezone(pytz.UTC)
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_utc.isoformat(),
                timeMax=end_utc.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            busy_times = []
            for event in events:
                start = event.get('start', {})
                end = event.get('end', {})
                
                if 'dateTime' in start:
                    start_dt = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
                    
                    # Convert back to local timezone
                    start_local = start_dt.astimezone(self.timezone)
                    end_local = end_dt.astimezone(self.timezone)
                    
                    busy_times.append({
                        'start': start_local,
                        'end': end_local
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
    
    def find_matching_slots(self, lead_availability: List[Dict], duration_minutes: int = 30) -> List[Dict]:
        """Find calendar slots that match lead's availability - FIXED VERSION"""
        matching_slots = []
        
        for slot in lead_availability:
            if slot.get('parsed_datetime'):
                try:
                    # Parse the datetime and make it timezone-aware
                    lead_time = datetime.fromisoformat(slot['parsed_datetime'])
                    
                    # Make sure it's timezone-aware
                    if lead_time.tzinfo is None:
                        lead_time = self.timezone.localize(lead_time)
                    
                    # Skip weekends
                    if lead_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
                        continue
                    
                    # Skip past times
                    now = datetime.now(self.timezone)
                    if lead_time < now:
                        continue
                    
                    # Check if this time is available in calendar
                    if self.is_time_available(lead_time, duration_minutes):
                        matching_slots.append({
                            'original_slot': slot,
                            'proposed_time': lead_time.replace(tzinfo=None),  # Remove timezone for storage
                            'display': lead_time.strftime("%A, %B %d at %I:%M %p"),
                            'confidence': slot.get('confidence', 0.5)
                        })
                except Exception as e:
                    print(f"Error parsing lead time {slot.get('parsed_datetime')}: {e}")
                    continue
        
        # Sort by confidence and time
        matching_slots.sort(key=lambda x: (-x['confidence'], x['proposed_time']))
        return matching_slots

    def is_time_available(self, check_time: datetime, duration_minutes: int) -> bool:
        """Check if a specific time slot is available - FIXED VERSION"""
        try:
            # Make sure check_time is timezone-aware
            if check_time.tzinfo is None:
                check_time = self.timezone.localize(check_time)
            
            end_time = check_time + timedelta(minutes=duration_minutes)
            
            # Get busy times for that day
            start_of_day = check_time.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            
            busy_times = self.get_busy_times(start_of_day, end_of_day)
            
            # Check for conflicts
            for busy in busy_times:
                # Make sure busy times are timezone-aware
                busy_start = busy['start']
                busy_end = busy['end']
                
                if busy_start.tzinfo is None:
                    busy_start = self.timezone.localize(busy_start)
                if busy_end.tzinfo is None:
                    busy_end = self.timezone.localize(busy_end)
                
                if (check_time < busy_end and end_time > busy_start):
                    return False
            
            return True
            
        except Exception as e:
            print(f"Error checking time availability: {e}")
            return False

    def suggest_alternative_times(self, around_time: datetime, num_suggestions: int = 3) -> List[Dict]:
        """Suggest alternative times around a preferred time - FIXED VERSION"""
        suggestions = []
        
        try:
            # Make sure around_time is timezone-aware
            if around_time.tzinfo is None:
                around_time = self.timezone.localize(around_time)
            
            # Start from the next business day if the requested time is in the past or weekend
            now = datetime.now(self.timezone)
            if around_time < now or around_time.weekday() >= 5:
                # Find next Monday
                days_until_monday = (7 - around_time.weekday()) % 7
                if days_until_monday == 0:  # It's already Monday
                    days_until_monday = 7
                around_time = around_time + timedelta(days=days_until_monday)
                around_time = around_time.replace(hour=10, minute=0, second=0, microsecond=0)
            
            base_date = around_time.replace(minute=0, second=0, microsecond=0)
            
            # Try different times around the preferred time
            time_offsets = [0, 1, -1, 2, -2, 3, -3, 24, -24, 48]  # Hours offset
            day_offsets = [0, 1, 2, 3, 4]  # Days offset
            
            for day_offset in day_offsets:
                for hour_offset in time_offsets:
                    candidate_time = base_date + timedelta(days=day_offset, hours=hour_offset)
                    
                    # Skip weekends
                    if candidate_time.weekday() >= 5:
                        continue
                    
                    # Skip outside business hours
                    if candidate_time.hour < 9 or candidate_time.hour > 17:
                        continue
                    
                    # Skip past times
                    if candidate_time < now:
                        continue
                    
                    if self.is_time_available(candidate_time, 30):
                        suggestions.append({
                            'time': candidate_time.replace(tzinfo=None),  # Remove timezone for storage
                            'display': candidate_time.strftime("%A, %B %d at %I:%M %p")
                        })
                        
                        if len(suggestions) >= num_suggestions:
                            break
                if len(suggestions) >= num_suggestions:
                    break
            
            return suggestions
            
        except Exception as e:
            print(f"Error suggesting alternative times: {e}")
            return []
    
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
