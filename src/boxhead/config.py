#!/usr/bin/env python3
"""Configuration of the application."""

import configparser
import pathlib
import pkg_resources

from boxhead.boxheadlogging import boxheadlogging

logger: boxheadlogging.BoxHeadLogger = boxheadlogging.get_logger(__name__)

class Config():
    """Representation of the configuration.

    Configuration can be set in two different ways:
    * APPLICATION_PATH/settings/config.ini (application's defaults)
    * path specified in config above (~/.config/boxcontroller/config.ini)
    * script params
    Where the latter configurations override the former configurations.
    """

    def __init__(self) -> None:
        """Initialise variables and load config from file(s).
        """
        #self.load()

    def load(self) -> None:
        self._config: configparser.ConfigParser = configparser.ConfigParser(
                interpolation=None)
        # load from APPLICATION_PATH/settings/config.ini
        path: pathlib.Path = pathlib.Path(pkg_resources.resource_filename(
            __name__,
            'settings/config.ini'))
        self._load(path)
        # load from user directory
        path = pathlib.Path(self.get('Paths', 'user_config'), 'config.ini')
        path = path.expanduser().resolve()
        self._load(path)

    def _load(self, path: pathlib.Path) -> None:
        """Load config from file.

        Positional arguments:
        config -- configparser.ConfigParser()
        path -- Path to load config from
        """
        try:
            with open(path, 'r', encoding='utf-8') as configfile:
                self._config.read_file(configfile)
        except FileNotFoundError:
            pass
            logger.debug('could not open config file at ' + str(path))
        else:
            pass
            logger.debug('loaded config from: ' + str(path))

    def get(self, *args, default=None, variable_type=None):
        """Return the specified configuration or default.

        Positional arguments:
        *args -- string(s), section / key to get

        Keyword arguments:
        default -- the default to return
        variable_type -- string, the type ("int", "float" or "boolean")
        """
        if variable_type == 'int':
            return self._config.getint(*args, fallback=default)
        elif variable_type == 'float':
            return self._config.getfloat(*args, fallback=default)
        elif variable_type == 'boolean':
            return self._config.getboolean(*args, fallback=default)
        else:
            return self._config.get(*args, fallback=default)

    def set(self, section, field, value):
        """Set a config value manually.

        Positional arguments:
        section -- string the section
        field -- string the key
        value -- string the value to set
        """
        try:
            self._config[section][field] = value
        except KeyError:
            pass
            logger.debug('could not set config value for "%s"."%s" to "%s"',
                    section, field, value)
