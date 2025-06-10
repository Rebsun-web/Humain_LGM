from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import enum
from config import config

Base = declarative_base()
engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

class LeadStatus(enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    RESPONDED = "responded"
    INTERESTED = "interested"
    MEETING_REQUESTED = "meeting_requested"
    MEETING_SCHEDULED = "meeting_scheduled"
    NOT_INTERESTED = "not_interested"
    FOLLOW_UP = "follow_up"

class CommunicationChannel(enum.Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    LINKEDIN = "linkedin"

class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    company_name = Column(String(200))
    company_website = Column(String(200))
    phone_number = Column(String(50))
    linkedin_url = Column(String(200))
    email = Column(String(200), unique=True)
    email_verified = Column(Boolean, default=False)
    status = Column(Enum(LeadStatus), default=LeadStatus.NEW)
    last_contact_date = Column(DateTime)
    next_follow_up_date = Column(DateTime)
    conversation_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    custom_data = Column(JSON, default={})

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer)
    channel = Column(Enum(CommunicationChannel))
    direction = Column(String(10))  # 'inbound' or 'outbound'
    message_content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    read = Column(Boolean, default=False)
    metadata = Column(JSON, default={})

class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer)
    scheduled_time = Column(DateTime)
    duration_minutes = Column(Integer, default=30)
    meeting_link = Column(String(500))
    calendar_event_id = Column(String(200))
    status = Column(String(50))  # 'proposed', 'confirmed', 'completed', 'cancelled'
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)
