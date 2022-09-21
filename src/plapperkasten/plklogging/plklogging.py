#!/usr/bin/env python3
"""Logging for all processes in the project."""

import logging as log
from logging import config as logging_config
from logging import handlers
import multiprocessing

logging_config.dictConfig({
    'version': 1,
    'formatters': {
        'detailed': {
            'format': '%(asctime)s %(name)-15s %(levelname)-8s %(message)s',
        },
        'simple': {
            'format': '%(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        #'file': {
        #    'class': 'logging.handlers.RotatingFileHandler',
        #    'filename': 'plapperkasten.log',
        #    'mode': 'a',
        #    'maxBytes': 10000000,
        #    'backupCount': 5,
        #    'formatter': 'detailed',
        #},
        #'errors': {
        #    'class': 'logging.handlers.RotatingFileHandler',
        #    'filename': 'plapperkasten-errors.log',
        #    'mode': 'a',
        #    'maxBytes': 10000000,
        #    'backupCount': 5,
        #    'level': 'ERROR',
        #    'formatter': 'detailed',
        #},
    },
    'root': {
        'level': 'DEBUG'
    },
    'loggers': {
        'logging_thread': {
            'handlers': ['console'],
            #'handlers': ['console', 'file', 'errors'],
            'level': 'DEBUG',
            'propagate': False
        },
    },
})

logger_queue: multiprocessing.Queue = multiprocessing.Queue(-1)
root: log.Logger = log.getLogger()
root.addHandler(handlers.QueueHandler(logger_queue))

class PlkLogger(log.Logger):
    """Wrapper around logging.Logger.

    Needed so that other modules do not need to import `logging` for
    type hinting the logger object.
    """

    def __init__(self, logger: log.Logger) -> None:
        # pylint: disable=super-init-not-called
        """Takes a logger instance and wraps itself around it.

        Args:
            logger: Instance of `logging.Logger`.
        """

        self.__class__ = type(logger.__class__.__name__,
                              (self.__class__, logger.__class__),
                              {})
        self.__dict__ = logger.__dict__

def get_logger(name: str = '') -> PlkLogger:
    """Wrapper aroung logging.getLogger().

    Args:
        name: The name of the logger to return, empty for root.
    """

    if name == '':
        return PlkLogger(log.getLogger())
    return PlkLogger(log.getLogger(name))

def get_queue() -> multiprocessing.Queue:
    """Return the queue used in the multiprocessing setup.

    Returns:
        The queue used by logging.handlers.QueueHandler().
    """

    return logger_queue
