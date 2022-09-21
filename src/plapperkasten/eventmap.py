#!/usr/bin/env python3
"""Map events."""

import pathlib
import pkg_resources

from plapperkasten import config as plkconfig
from plapperkasten import event
from plapperkasten import keymap
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class EventMap(keymap.KeyMap):
    """Representation of the two event map files.

    Events are mapped in two different files:
    * APPLICATION_PATH/settings/events.map (application's default)
    * USER_DIR/events.map
    Whereas events from the latter file override events from the
    former.

    Events are specified one per line.
    For the general form see KeyMap.

    Attributes:
        _path_user_map: The path to the map provided by the user.
    """

    def __init__(self, config: plkconfig.Config) -> None:
        """Initialise variables and load map from file(s).

        Args:
            config: The configuration.
        """
        super().__init__(config)
        self._path_user_map: pathlib.Path = pathlib.Path(
            config.get_str('core',
                           'paths',
                           'user_directory',
                           default='~/.config/plapperkasten/'),
            config.get_str('core', 'paths', 'eventmap', default='events.map'))
        self._path_user_map = self._path_user_map.expanduser().resolve()
        self.reset()

    def reset(self) -> None:
        """Reset variables and reload."""
        super().reset()
        self.load()

    def get_path_user_map(self) -> pathlib.Path:
        """Return the path to the map provided by the user."""
        return self._path_user_map

    def load(self) -> None:
        """(Re-)read the mapping files."""
        # load from APPLICATION_PATH/settings/events.map
        self._load(
            pathlib.Path(
                pkg_resources.resource_filename(__name__,
                                                'settings/events.map')))
        # load from USER_DIR/events.map
        self._load(self.get_path_user_map())

    def get_event(self, key: str) -> event.Event:
        """Return the event mapped to the key or None.

        Args:
            key: The key.

        Returns:
            The event data.
        """

        try:
            item: keymap.KeyMapItem = self.get(key)
            return event.Event(item.values[0], *item.values[1:],
                               **item.params.copy())
        except KeyError as e:
            logger.error('no event for key: "%s"', key)
            raise KeyError from e
        except IndexError:
            return event.Event('')

    def update_event(self, key: str, event_name: str, *values: str,
                     **params: str) -> None:
        """Update, add or delete the mapping of an event.

        Args:
            key: The key.
            event: The name of the event. Leave empty to remove entry.
            *values: Values to store.
            **params: Parameters to store.
        """

        if event_name == '':
            self.remove_event(key)
        values = (event_name, *values)
        self.update(self.get_path_user_map(), key, *values, **params)

    def remove_event(self, key: str) -> None:
        """Remove event with key.

        Args:
            key: The key.
        """
        self.remove(self.get_path_user_map(), key)
