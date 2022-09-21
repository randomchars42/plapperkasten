#!/usr/bin/env python3
"""Configuration of the application."""

import yaml
import pathlib
import pkg_resources

from typing import Any, TypeVar, Callable

from plapperkasten.plklogging import plklogging

T = TypeVar('T')
U = TypeVar('U')
V = TypeVar('V')
W = TypeVar('W')

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Config():
    """Representation of the configuration.

    Configuration can be set in several different ways:
    * APPLICATION_PATH/settings/config.yml (application's defaults)
    * each plugin's config.yaml
    * user's config file (default: ~/.config/plapperkasten/config.yaml)
    * script params
    Where the latter configurations override the former configurations.

    Provides functions that will convert the retrieved or set values.

    Attributes:
        _config_default: Dictionary holding the configuration as
            specified the programme / plugin.
        _config_user: Dictionary holding the configuration as specified
            by the user in the user's config file (default:
            ~/.config/plapperkasten/config.yaml)
        _config_input: Dictionary holding the configuration specified
            via the CLI.
        _config_active: Dictionary holding the consolidated version of
            all configurations
        _consolidated: Have the sources of configuration been merged
            yet?
    """

    def __init__(self) -> None:
        """Initialise variables and load config from file(s).
        """

        self._config_default: dict[str, Any] = {}
        self._config_user: dict[str, Any] = {}
        self._config_input: dict[str, Any] = {}
        self._config_active: dict[str, Any] = {}
        self._consolidated = True
        self.load()

    def load(self) -> None:
        """Try to load config.yaml from several locations."""

        # load from APPLICATION_PATH/settings/config.ini
        path: pathlib.Path = pathlib.Path(
            pkg_resources.resource_filename(__name__, 'settings/config.yaml'))
        self.load_from_path(path, 'default')
        # load from user directory
        path = pathlib.Path(
            self.get_str('core', 'paths', 'user_directory', default=''),
            'config.yaml')
        path = path.expanduser().resolve()
        if path.exists():
            self.load_from_path(path, 'user')

    def load_from_path(self,
                       path: pathlib.Path,
                       target: str = 'default') -> None:
        """Load config from file.

        Args:
            path: Path to load config from.
            target: The id of the dictionary to laod the config into.
        """

        try:
            with open(path, 'r', encoding='utf-8') as configfile:

                if target == 'user':
                    self.merge_dicts(self._config_user,
                                     yaml.safe_load(configfile))
                elif target == 'input':
                    self.merge_dicts(self._config_input,
                                     yaml.safe_load(configfile))
                else:
                    self.merge_dicts(self._config_default,
                                     yaml.safe_load(configfile))
            self._consolidated = False
        except yaml.YAMLError:
            logger.debug('error while parsing %s', str(path))
        except FileNotFoundError:
            logger.debug('could not open config file at %s', str(path))
        else:
            logger.debug('loaded config from: %s', str(path))

    def consolidate_config(self):
        """Merge configuration from different sources.

        Will be called before `_get()` / `get_*` if `_consolidated` is
        `False`.

        It will then take the configuration from the built-in
        `config.yaml` files as a basis and update it with the
        configuration from the user's `config.yaml` and last the
        script parameters if any.
        """

        self._config_active = {}
        self._config_active = self.merge_dicts(self._config_active,
                                               self._config_default)
        self._config_active = self.merge_dicts(self._config_active,
                                               self._config_user)
        self._config_active = self.merge_dicts(self._config_active,
                                               self._config_input)
        self._consolidated = True

    def merge_dicts(self,
                    a: dict[Any, Any],
                    b: dict[Any, Any],
                    path: list[Any] = None) -> dict[Any, Any]:
        """Merges dictionary b into a.

        Args:
            a: The dictionary to get updated.
            b: The dictionary to merge into a.
            path: A "path" (lsit of keys) to the current leaf.

        Returns:
            The final dictionary.
        """

        # Found here:
        # <https://stackoverflow.com/questions/7204805/how-to-merge-dictionaries-of-dictionaries>
        if path is None:
            path = []
        for key in b:
            if key in a:
                if isinstance(a[key], dict) and isinstance(b[key], dict):
                    self.merge_dicts(a[key], b[key], path + [str(key)])
                elif a[key] == b[key]:
                    pass  # same leaf value
                elif hasattr(b[key], 'copy'):
                    a[key] = b[key].copy()
                else:
                    a[key] = b[key]
            else:
                if hasattr(b[key], 'copy'):
                    a[key] = b[key].copy()
                else:
                    a[key] = b[key]
        return a

    def _get_last_branch(self, *path: str, config_part: dict) -> dict:
        """Return the last branch, a dict, before the leave.

        Creates the path if it doesn't exist.

        Args:
            *path: The path to the value to get.
            default: The default to return.

        Returns:
            The config value.
        """

        if len(path) > 2:
            # there are more nodes on the path than just the leave and
            # the last branch
            if not path[0] in config_part:
                # create the node if necessary
                config_part[path[0]] = {}
            # and walk on popping the current node off the path
            return self._get_last_branch(*path[1:],
                                         config_part=config_part[path[0]])
        elif len(path) == 2:
            # we've reached the last branch
            if not path[0] in config_part:
                config_part[path[0]] = {}
            return config_part[path[0]]
        else:
            # we've reached the leave
            # this can only happen if the path was too short
            raise ValueError('Path too short.')

    def _get(self,
             *path: str,
             default: T,
             convert: Callable[[T], T] = lambda t: t) -> T:
        """Return the specified configuration or default.


        Args:
            *path: The path to the value to get.

        Returns:
            The config value or the default value.

        Raises:
            ValueError: If no path is given or the path is only two
                items long (['core'|'plugins'].SECTION instead of
                ['core'|'plugins'].SECTION.[KEY|PATH]) ValueError
                is raised.
        """

        if len(path) <= 2:
            raise ValueError('Path too short.')

        if not self._consolidated:
            self.consolidate_config()

        last_branch: dict[str, Any] = self._get_last_branch(
            *path, config_part=self._config_active)

        # will throw an uncaught error and thus expose invalid defaults
        value: T = convert(default)

        if not path[-1] in last_branch:
            logger.error('no configuration for "%s"', '.'.join(path))
        else:
            try:
                value = convert(last_branch[path[-1]])
            except ValueError:
                logger.error('value for "%s" could not be converted',
                             '.'.join(path))

        return value

    def get_int(self, *path: str, default: int) -> int:
        """Return the configuration or default, see Config.get()."""
        return self._get(*path, default=default, convert=int)

    def get_str(self, *path: str, default: str) -> str:
        """Return the configuration or default, see Config.get()."""
        return self._get(*path, default=default, convert=str)

    def get_bool(self, *path: str, default: bool) -> bool:
        """Return the configuration or default, see Config.get()."""
        return self._get(*path, default=default, convert=bool)

    def get_list_int(self, *path: str, default: list[int]) -> list[int]:
        """Return the configuration or default, see Config.get()."""
        return self._get(*path,
                         default=default,
                         convert=lambda l: self._convert_list(l, int)).copy()

    def get_list_str(self, *path: str, default: list[str]) -> list[str]:
        """Return the configuration or default, see Config.get()."""
        return self._get(*path,
                         default=default,
                         convert=lambda l: self._convert_list(l, str)).copy()

    def get_list_bool(self, *path: str, default: list[bool]) -> list[bool]:
        """Return the configuration or default, see Config.get()."""
        return self._get(*path,
                         default=default,
                         convert=lambda l: self._convert_list(l, bool)).copy()

    def get_dict_int_int(self, *path: str,
                         default: dict[int, int]) -> dict[int, int]:
        """Return the configuration or default, see Config.get()."""
        return self._get(
            *path,
            default=default,
            convert=lambda d: self._convert_dict(d, int, int)).copy()

    def get_dict_int_str(self, *path: str,
                         default: dict[int, str]) -> dict[int, str]:
        """Return the configuration or default, see Config.get()."""
        return self._get(
            *path,
            default=default,
            convert=lambda d: self._convert_dict(d, int, str)).copy()

    def get_dict_int_bool(self, *path: str,
                          default: dict[int, bool]) -> dict[int, bool]:
        """Return the configuration or default, see Config.get()."""
        return self._get(
            *path,
            default=default,
            convert=lambda d: self._convert_dict(d, int, bool)).copy()

    def get_dict_str_int(self, *path: str,
                         default: dict[str, int]) -> dict[str, int]:
        """Return the configuration or default, see Config.get()."""
        return self._get(
            *path,
            default=default,
            convert=lambda d: self._convert_dict(d, str, int)).copy()

    def get_dict_str_str(self, *path: str,
                         default: dict[str, str]) -> dict[str, str]:
        """Return the configuration or default, see Config.get()."""
        return self._get(
            *path,
            default=default,
            convert=lambda d: self._convert_dict(d, str, str)).copy()

    def get_dict_str_bool(self, *path: str,
                          default: dict[str, bool]) -> dict[str, bool]:
        """Return the configuration or default, see Config.get()."""
        return self._get(
            *path,
            default=default,
            convert=lambda d: self._convert_dict(d, str, bool)).copy()

    def _set(self,
             *path,
             value: Any,
             convert: Callable[[Any], Any],
             target: str = 'default') -> None:
        """Set a config value manually.

        Args:
            *path: The path to the value to set.
            value: The value.
            target: The target.

        Raises:
            ValueError: If no path or the path is only two items long
                ('core' / 'plugins') is given ValueError is raised
                instead of returning the whole config dict.
        """

        if len(path) <= 2:
            raise ValueError('Path too short.')

        config: dict[str, Any]

        if target == 'user':
            config = self._config_user
        elif target == 'input':
            config = self._config_input
        else:
            config = self._config_default

        last_branch: dict[str, Any] = self._get_last_branch(*path,
                                                            config_part=config)

        last_branch[path[-1]] = convert(value)
        self._consolidated = False

    def set_int(self, *path: str, value: int, target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path, value=value, convert=int, target=target)

    def set_str(self, *path: str, value: str, target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path, value=value, convert=str, target=target)

    def set_bool(self, *path: str, value: bool, target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path, value=value, convert=bool, target=target)

    def set_list_int(self,
                     *path: str,
                     value: list[int],
                     target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda l: self._convert_list(l, int),
                  target=target)

    def set_list_str(self,
                     *path: str,
                     value: list[str],
                     target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda l: self._convert_list(l, str),
                  target=target)

    def set_list_bool(self,
                      *path: str,
                      value: list[bool],
                      target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda l: self._convert_list(l, bool),
                  target=target)

    def set_dict_int_int(self,
                         *path: str,
                         value: dict[int, int],
                         target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda d: self._convert_dict(d, int, int),
                  target=target)

    def set_dict_int_str(self,
                         *path: str,
                         value: dict[int, str],
                         target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda d: self._convert_dict(d, int, str),
                  target=target)

    def set_dict_int_bool(self,
                          *path: str,
                          value: dict[int, bool],
                          target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda d: self._convert_dict(d, int, bool),
                  target=target)

    def set_dict_str_int(self,
                         *path: str,
                         value: dict[str, int],
                         target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda d: self._convert_dict(d, str, int),
                  target=target)

    def set_dict_str_str(self,
                         *path: str,
                         value: dict[str, str],
                         target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda d: self._convert_dict(d, str, str),
                  target=target)

    def set_dict_str_bool(self,
                          *path: str,
                          value: dict[str, bool],
                          target: str = 'default'):
        """Set the value for a config path, see Config.set()."""
        self._set(*path,
                  value=value,
                  convert=lambda d: self._convert_dict(d, str, bool),
                  target=target)

    def _convert_list(self, convert_from: list[T],
                      convert: Callable[[T], U]) -> list[U]:
        """Convert all items in the list.

        Args:
            convert_from: The list to convert.
            convert: A function to convert the list items.

        Returns:
            The converted list.
        """

        try:
            return [convert(value) for value in convert_from]
        except TypeError as e:
            logger.error('no list given')
            raise ValueError from e

    def _convert_dict(self, convert_from: dict[T, U],
                      convert_keys: Callable[[T], V],
                      convert_values: Callable[[U], W]) -> dict[V, W]:
        """Converts all keys and values in the dict.

        Args:
            convert_from: The dict to convert.
            convert_keys: A function to convert the keys.
            convert_values: A function to convert the values.

        Returns:
            The converted dict.
        """

        try:
            return {
                convert_keys(key): convert_values(value)
                for key, value in convert_from.items()
            }
        except TypeError as e:
            logger.error('no dict given')
            raise ValueError from e
