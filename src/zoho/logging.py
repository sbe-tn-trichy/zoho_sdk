import os
import logging
from typing import Optional

def configure_logger(logger_name: str, log_filename: str) -> logging.Logger:
    """
    Configures a logger with a FileHandler in the tests/logs or logs directory,
    ensuring it is done dynamically without import-time side-effects.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)

    # Allow users to disable automated file logging
    if os.environ.get("ZOHO_DISABLE_FILE_LOGGING") == "true":
        return logger

    if not logger.handlers:
        project_root = os.environ.get("PROJECT_ROOT", os.getcwd())
        is_testing = "PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true"
        log_dir = os.path.join(project_root, "tests" if is_testing else "", "logs")
        
        try:
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, log_filename)
            
            # Use appropriate formatting depending on type of logger
            if "app" in logger_name:
                formatter = logging.Formatter('%(asctime)s - [APP] [ZOHO_WD] %(levelname)s - [%(funcName)s] - %(message)s')
            elif "api" in logger_name:
                formatter = logging.Formatter('%(asctime)s - [API] %(levelname)s - %(message)s')
            else:
                formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
                
            file_handler = logging.FileHandler(log_path, encoding='utf-8')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception:
            # Gracefully ignore if we cannot write logs to the filesystem (e.g. read-only system)
            pass
            
    return logger
