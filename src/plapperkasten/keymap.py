#!/usr/bin/env python3
"""Very simple file based database resembling CSV but using a key."""

import pathlib

from typing import Tuple

from plapperkasten import config as plkconfig
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)

class KeyMapItem():
    """An item representing a line in a keymap.

    Attributes:
        values: Values represented by this item.
        parameters: Parameters represented by this item.
    """
    __slots__ = ['values', 'params']

    def __init__(self) -> None:
        """Initialise attributes."""
        self.values: list[str] = []
        self.params: dict[str, str] = {}


class KeyMap():
    """Representation of data where a database would be too much.

    Information is stored in a plain utf-8 textfile like this:
    KEY|DATUM1|KEYWORD2=DATUM2|KEYWORD3=DATUM3|...

    The default delimiter is "|" but can be changed in the config.

    Information is looked up by a key (the first item in a line).

    Lines may be commented out by prefixing them with "#"

    Attributes:
        _delimiter: The delimiter between datapoints.
    """

    def __init__(self, config: plkconfig.Config) -> None:
        """Retrieve config values."""
        self._delimiter: str = config.get_str('core',
                                              'mapping',
                                              'delimiter',
                                              default='|')

    def reset(self) -> None:
        """Reset variables."""
        self._map: dict[str, KeyMapItem] = {}

    def get_delimiter(self) -> str:
        return self._delimiter

    def get_map(self) -> dict[str, KeyMapItem]:
        return self._map

    def load(self) -> None:
        """Load all maps into `_map`.

        As there is no default map this function does nothing and may
        be re-implemented by its children.
        """
        pass

    def _load(self, path: pathlib.Path) -> None:
        """Load map from file.

        Args:
            path: Path to load the map from.
        """

        path = pathlib.Path(path)
        mapping: dict[str, KeyMapItem] = {}

        try:
            with path.open('r', encoding='utf-8') as raw_map:
                lines: list[str] = raw_map.readlines()

            for line in lines:

                if line == '' or line[0] == '#':
                    # a comment
                    continue

                line = line.strip()

                try:
                    key, data = self._process_line(line)
                    mapping[key] = data
                except ValueError:
                    logger.error('malformed line: "%s"', line)
                    continue
        except FileNotFoundError:
            logger.debug('could not open file at  "%s"', str(path))
        else:
            logger.debug('loaded map: "%s"', str(path))

        self._map.update(mapping)

    def _process_line(self, raw_line: str) -> Tuple[str, KeyMapItem]:
        """Process a mapping line.

        Mapping lines are formatted like this:
        KEY|DATUM1|KEYWORD2=DATUM2|KEYWORD3=DATUM3|...

        Args:
            raw_line: The raw line to parse.

        Returns:
            A tuple containing the key and the KeyMapItem.
        """
        if raw_line == '':
            raise ValueError('empty mapping given')

        key: str = ''
        rest: list[str] = []
        key, *rest = raw_line.split(self.get_delimiter())

        item: KeyMapItem = KeyMapItem()

        for raw in rest:
            raw = raw.strip()
            pieces: list[str] = raw.split('=', 1)
            if len(pieces) == 1:
                item.values.append(pieces[0])
            else:
                item.params[pieces[0]] = pieces[1]

        return (key, item)

    def get(self, key: str) -> KeyMapItem:
        """Return the entry mapped to the key or an empty item.

        Args:
            key: The key.

        Returns:
            The KeyMapItem bound to the key or an empty KeyMapItem.
        """
        try:
            return self.get_map()[key]
        except KeyError:
            logger.error('no entry for key: "%s"', key)
            return KeyMapItem()

    def _to_map_line(self, key: str, *values: str, **params: str) -> str:
        """Convert values and params to a map line.

        Args:
            key: The key:
            values: Values.
            params: A dict containing parameters
        """

        flattend_params = [f'{key}={value}' for (key, value) in params.items()]

        return self.get_delimiter().join([key, *values, *flattend_params])

    def update(self, path: pathlib.Path, mapkey: str, *values: str,
               **params: str) -> None:
        """Update, add or delete an entry.

        Args:
            path: The path of the file.
            mapkey: The key.
            *values: Values to store. Leave empty to remove entry.
            **params: Parameters to store. Leave empty to remove entry.
        """

        path = pathlib.Path(path)

        logger.debug(
            'updating keymap at "%s" for key "%s" with: %s,%s', path, mapkey,
            ','.join(values),
            ','.join([f'{kw}={v}'.format(kw, v) for kw, v in params.items()]))

        try:
            with path.open('r', encoding='utf-8') as keymap:
                lines: list[str] = keymap.readlines()
        except FileNotFoundError:
            logger.debug('could not open file at %s', str(path))
            lines = []

        key_length: int = len(mapkey)
        done: bool = False

        for i, line in enumerate(lines):
            if line[:key_length + 1] == mapkey + self.get_delimiter():
                # the key is already mapped
                # make sure we don't accidentally catch a longer key by adding
                # the required delimiter to the end of the key
                if len(values) > 0 or len(params) > 0:
                    # update the mapping
                    lines[i] = self._to_map_line(mapkey, *values, **
                                                 params) + '\n'
                    logger.debug('updated entry for key "%s"', mapkey)
                else:
                    # remove the mapping
                    lines.pop(i)
                    logger.debug('removed entry for key "%s"', mapkey)
                done = True
                break

        if not done and (len(values) > 0 or len(params) > 0):
            # there was no mapping so append it
            lines.append(self._to_map_line(mapkey, *values, **params) + '\n')
            logger.info('added entry for key "%s"', mapkey)

        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

        with path.open('w', encoding='utf-8') as keymap:
            keymap.write(''.join(lines))
            logger.debug('updated map: "%s"', path)

        self.reset()

    def remove(self, path: pathlib.Path, key: str) -> None:
        """Remove entry with key.

        Args:
            path: The path of the file.
            key: The key of the data to remove.
        """
        self.update(path, key)
