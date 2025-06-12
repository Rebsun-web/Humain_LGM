from contextlib import contextmanager
from typing import Generator
from lead_processing_manager.Models.models import SessionLocal, Base, engine
import logging

logger = logging.getLogger(__name__)

def init_database():
    """Initialize the database and create all tables"""
    try:
        logger.info("Initializing database...")
        Base.metadata.create_all(engine)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}", exc_info=True)
        raise

@contextmanager
def db_session() -> Generator:
    """Context manager for database sessions"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()
