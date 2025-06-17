# db_utils.py
import time
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from lead_processing_manager.Configs.config import config

# Use Python's built-in logging instead of the custom setup_logger
logger = logging.getLogger(__name__)

# Create engine with better settings for SQLite
engine = create_engine(
    config.DATABASE_URL,
    connect_args={
        'timeout': 30,  # 30 second timeout
        'check_same_thread': False,
        'isolation_level': None  # Use autocommit mode
    },
    pool_pre_ping=True,
    pool_recycle=3600
)

# Enable WAL mode for better concurrency
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")  # 30 second busy timeout
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def db_session(max_retries=5, initial_delay=0.1):
    """Create a database session with retry logic for locked database"""
    session = None
    delay = initial_delay
    
    for attempt in range(max_retries):
        try:
            session = SessionLocal()
            yield session
            session.commit()
            break
        except OperationalError as e:
            if session:
                session.rollback()
            
            if "database is locked" in str(e) and attempt < max_retries - 1:
                logger.warning(f"Database locked, attempt {attempt + 1}/{max_retries}. Waiting {delay}s...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
                continue
            else:
                logger.error(f"Database error after {attempt + 1} attempts: {e}")
                raise
        except Exception as e:
            if session:
                session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if session:
                session.close()