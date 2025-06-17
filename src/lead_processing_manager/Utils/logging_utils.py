import logging
import sys
import traceback
from functools import wraps
from typing import Callable, Any
import inspect
from lead_processing_manager.Utils.db_utils import db_session


# Configure logging
def setup_logger(name: str) -> logging.Logger:
    """Set up a logger with enhanced formatting and handlers."""
    logger = logging.getLogger(name)
    
    if not logger.handlers:  # Avoid adding handlers multiple times
        logger.setLevel(logging.DEBUG)
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
        )
        
        # File handler with detailed formatting
        file_handler = logging.FileHandler('lead_processor.log')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        
        # Console handler with color coding
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(detailed_formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    
    return logger

def log_error(logger: logging.Logger, error: Exception, context: str = None) -> None:
    """Log an error with full stack trace and context."""
    stack_trace = ''.join(traceback.format_tb(error.__traceback__))
    error_type = type(error).__name__
    error_msg = str(error)
    
    # Get the caller's frame information
    caller_frame = inspect.currentframe().f_back
    caller_info = inspect.getframeinfo(caller_frame)
    
    error_location = f"{caller_info.filename}:{caller_info.lineno}"
    
    log_message = (
        f"\nError Location: {error_location}"
        f"\nError Type: {error_type}"
        f"\nError Message: {error_msg}"
        f"\nContext: {context if context else 'No context provided'}"
        f"\nStack Trace:\n{stack_trace}"
    )
    
    logger.error(log_message)

def log_function_call(logger: logging.Logger) -> Callable:
    """Decorator to log function entry, exit, and any errors."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            func_name = func.__name__
            try:
                logger.debug(f"Entering {func_name} with args={args}, kwargs={kwargs}")
                result = await func(*args, **kwargs)
                logger.debug(f"Exiting {func_name} successfully")
                return result
            except Exception as e:
                log_error(
                    logger,
                    e,
                    f"Error in async function {func_name} with args={args}, kwargs={kwargs}"
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            func_name = func.__name__
            try:
                logger.debug(f"Entering {func_name} with args={args}, kwargs={kwargs}")
                result = func(*args, **kwargs)
                logger.debug(f"Exiting {func_name} successfully")
                return result
            except Exception as e:
                log_error(
                    logger,
                    e,
                    f"Error in function {func_name} with args={args}, kwargs={kwargs}"
                )
                raise
        
        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
    return decorator
