"""
FREIGHTINFO_MARAD Runbook - Logging Configuration
Dual file + console logging with timestamped log files.
"""

import os
import logging
import config


def setup_logging():
    """Configure logging for the application."""
    os.makedirs(config.LOG_DIR, exist_ok=True)

    log_file = os.path.join(config.LOG_DIR, config.LOG_FILE_PATTERN)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.LOG_LEVEL))

    # Clear existing handlers
    root_logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if config.LOG_TO_FILE:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(getattr(logging, config.LOG_LEVEL))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if config.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, config.LOG_LEVEL))
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    logging.info('=' * 70)
    logging.info(f'Logging initialized: {log_file}')
    logging.info('=' * 70)

    return log_file
