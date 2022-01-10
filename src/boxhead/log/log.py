#!/usr/bin/env python3
"""Dictionary configuration for logging."""

config = {
    'version': 1,
    'formatters': {
        'detailed': {
            'format':
            '%(asctime)s %(name)-15s %(levelname)-8s %(message)s',
        },
        'simple': {
            'format': '%(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            #'level': 'INFO',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'boxhead.log',
            'mode': 'a',
            'maxBytes': 10000000,
            'backupCount': 5,
            'formatter': 'detailed',
        },
        'errors': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'boxhead-errors.log',
            'mode': 'a',
            'maxBytes': 10000000,
            'backupCount': 5,
            'level': 'ERROR',
            'formatter': 'detailed',
        },
    },
    'root': {
        'level': 'DEBUG',
        'handlers': ['console', 'file', 'errors']
    },
}
