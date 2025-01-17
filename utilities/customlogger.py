import logging
import os

def setup_logger(name="ProjectLog", log_level=logging.INFO, log_to_file=False, log_file_path="logs/app.log"):
    """
    Setup a centralized logger.
    :param log_level: Logging level (e.g., logging.DEBUG, logging.INFO).
    :param log_to_file: Whether to log messages to a file.
    :param log_file_path: Path to the log file.
    :return: Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Prevent duplicate handlers if setup_logger is called multiple times
    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        if log_to_file:
            # Ensure the log directory exists
            os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
            # File handler
            file_handler = logging.FileHandler(log_file_path)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger


# Initialize the logger once
logger = setup_logger(name="GenAIPOT", log_level=logging.DEBUG, log_to_file=True, log_file_path="logs/app.log")