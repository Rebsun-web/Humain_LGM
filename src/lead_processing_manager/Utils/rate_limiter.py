import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any
from lead_processing_manager.Configs.config import Config


class WhatsAppRateLimiter:
    def __init__(self):
        self.rate_file = "whatsapp_usage.json"
        self.daily_limit = Config.WHATSAPP_DAILY_LIMIT
        self.hourly_limit = Config.WHATSAPP_HOURLY_LIMIT
        self.usage_data = self._load_usage_data()
    
    def _load_usage_data(self) -> Dict[str, Any]:
        """Load usage data from file"""
        if os.path.exists(self.rate_file):
            try:
                with open(self.rate_file, 'r') as f:
                    data = json.load(f)
                    # Convert string dates back to datetime
                    if 'last_reset' in data:
                        data['last_reset'] = datetime.fromisoformat(data['last_reset'])
                    if 'hourly_reset' in data:
                        data['hourly_reset'] = datetime.fromisoformat(data['hourly_reset'])
                    return data
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Default data structure
        return {
            'daily_count': 0,
            'hourly_count': 0,
            'last_reset': datetime.now(),
            'hourly_reset': datetime.now(),
            'total_sent': 0
        }
    
    def _save_usage_data(self):
        """Save usage data to file"""
        try:
            # Convert datetime objects to strings for JSON serialization
            save_data = self.usage_data.copy()
            save_data['last_reset'] = save_data['last_reset'].isoformat()
            save_data['hourly_reset'] = save_data['hourly_reset'].isoformat()
            
            with open(self.rate_file, 'w') as f:
                json.dump(save_data, f)
        except Exception as e:
            print(f"Error saving rate limit data: {e}")
    
    def _reset_counters_if_needed(self):
        """Reset counters if time periods have elapsed"""
        now = datetime.now()
        
        # Reset daily counter if it's a new day
        if now.date() > self.usage_data['last_reset'].date():
            self.usage_data['daily_count'] = 0
            self.usage_data['last_reset'] = now
            print(f"Daily WhatsApp counter reset. New limit: {self.daily_limit}")
        
        # Reset hourly counter if an hour has passed
        if now >= self.usage_data['hourly_reset'] + timedelta(hours=1):
            self.usage_data['hourly_count'] = 0
            self.usage_data['hourly_reset'] = now
            print(f"Hourly WhatsApp counter reset. New limit: {self.hourly_limit}")
        
        self._save_usage_data()
    
    def can_send_message(self) -> tuple[bool, str]:
        """Check if we can send a WhatsApp message"""
        self._reset_counters_if_needed()
        
        # Check daily limit
        if self.usage_data['daily_count'] >= self.daily_limit:
            return False, f"Daily limit reached ({self.daily_limit}). Resets tomorrow."
        
        # Check hourly limit
        if self.usage_data['hourly_count'] >= self.hourly_limit:
            return False, f"Hourly limit reached ({self.hourly_limit}). Resets in {60 - datetime.now().minute} minutes."
        
        return True, "OK"
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics"""
        self._reset_counters_if_needed()
        
        return {
            'daily_count': self.usage_data['daily_count'],
            'daily_limit': self.daily_limit,
            'daily_remaining': self.daily_limit - self.usage_data['daily_count'],
            'hourly_count': self.usage_data['hourly_count'],
            'hourly_limit': self.hourly_limit,
            'hourly_remaining': self.hourly_limit - self.usage_data['hourly_count'],
            'total_sent': self.usage_data['total_sent'],
            'can_send': self.can_send_message()[0]
        }