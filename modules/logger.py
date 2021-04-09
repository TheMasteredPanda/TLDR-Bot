import logging
import os
import sys

from logging import handlers

log_session = None


def get_logger(name: str = 'TLDR-Bot-log'):
    """
    Get logging session, or create it if needed.

    Parameters
    -----------
    name: :class:`str`
        Name of the file where logs will be put.

    Returns
    -------
    :class:`logging.LoggerAdapter`
        The logging adapter.
    """
    global log_session

    logger = logging.getLogger('TLDR')
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        log_path = os.path.join('logs/', f'{name}.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        formatter = logging.Formatter('{asctime} {levelname:<8} {message}', style='{')

        # sys
        sysh = logging.StreamHandler(sys.stdout)
        sysh.setLevel(logging.DEBUG)
        sysh.setFormatter(formatter)
        logger.addHandler(sysh)

        # Log file
        fh = logging.handlers.RotatingFileHandler(log_path, backupCount=2)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    adapter = logging.LoggerAdapter(logger, extra={'session': 2})
    return adapter
