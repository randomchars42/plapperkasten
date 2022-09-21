#!/usr/bin/env python3
"""Store the status of a playlist or folder."""

import pathlib

from plapperkasten import config as plkconfig
from plapperkasten import keymap
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Status:
    """Represention of the status of a playlist.

    The status comprises the following items:
    * name of the playlist / folder as the key
    * position of the last / currently playing song in the track list
    * position in the last / currently playing song (time)
    * the state (playing, stopped, paused)

    Attributes:
        key: The name of the playlist or folder. Playlists must
            end with `.m3u` or will be mistaken for folder.
        position: The position of the file within the playlist.
        elapsed: The time since beginning of the track.
        state: The state ("play", "stop", "pause", "n/a"). Will not be
            persisted in StatusMap
    """

    def __init__(self,
                 key: str = '',
                 position: str = '0',
                 elapsed: str = '0.000',
                 state: str = 'n/a') -> None:
        """Create default values."""
        self.key: str = key
        self.position: str = position
        self.elapsed: str = elapsed
        self.state: str = state


class StatusMap(keymap.KeyMap):
    """Persist the status of a playlist or folder (acting as playlist).

    The status will be stored under USER_DIR/mpdclient_status.map

    For the general form see KeyMap.

    Attributes:
        _path_map: The path to the map provided by the user.
    """

    def __init__(self, config: plkconfig.Config) -> None:
        """Initialise variables and load map from file(s).

        Args:
            config: The configuration.
        """
        super().__init__(config)
        self._path_map: pathlib.Path = pathlib.Path(
            config.get_str('core',
                           'paths',
                           'user_directory',
                           default='~/.config/plapperkasten/'),
            config.get_str('plugins',
                           'mpdclient',
                           'name_statusmap',
                           default='mpdclient_status.map'))
        self._path_map = self._path_map.expanduser().resolve()
        self.reset()

    def reset(self) -> None:
        """Reset variables and reload."""
        super().reset()
        self.load()

    def get_path_map(self) -> pathlib.Path:
        """Return the path to the map provided by the user."""
        return self._path_map

    def load(self) -> None:
        """(Re-)read the mapping file."""
        # load from USER_DIR/events.map
        self._load(self.get_path_map())

    def get_status(self, key: str) -> Status:
        """Return the event mapped to the key or None.

        Args:
            key: The key.

        Returns:
            The status.
        """

        try:
            item: keymap.KeyMapItem = self.get(key)
            return Status(key, item.values[0], item.values[1])
        except KeyError as e:
            logger.error('no event for key: "%s"', key)
            raise KeyError from e
        except IndexError:
            logger.error('index error')
            return Status()

    def update_status(self, status: Status) -> None:
        """Update, add or delete the mapping of a status.

        Args:
            status: The status.
        """

        self.update(self.get_path_map(), status.key, status.position,
                    status.elapsed)

    def remove_status(self, status: Status) -> None:
        """Remove the status.

        Args:
            status: The status.
        """
        self.remove(self.get_path_map(), status.key)
