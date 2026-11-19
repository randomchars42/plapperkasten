"""Spotify playlist links and the user's saved favorites."""

import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import yaml

from plapperkasten.config import Config


def playlist_uri(value: str) -> str:
    """Normalize a Spotify playlist URI or a full Spotify share link.

    Links are parsed locally; no URL is fetched or passed to a shell.
    """
    value = value.strip()
    if any(char.isspace() for char in value):
        raise ValueError('Enter a Spotify playlist link or URI.')
    match = re.fullmatch(r'spotify:playlist:([A-Za-z0-9]{22})', value)
    if not match:
        try:
            url = urlsplit(value)
        except ValueError as error:
            raise ValueError('Enter a Spotify playlist link or URI.') from error
        if url.scheme == 'https' and url.netloc == 'open.spotify.com':
            match = re.fullmatch(
                r'/(?:intl-[A-Za-z-]+/)?playlist/([A-Za-z0-9]{22})/?',
                url.path)
    if not match:
        raise ValueError('Enter a Spotify playlist link or URI.')
    return f'spotify:playlist:{match.group(1)}'


def playable_uri(value: str) -> str:
    """Accept a playlist link or a track/episode URI supplied by Soloist."""
    value = value.strip()
    if re.fullmatch(r'spotify:(?:track|episode):[A-Za-z0-9]{22}', value):
        return value
    return playlist_uri(value)


def favorites_path(config: Config) -> Path:
    """Resolve the favorites file relative to the user configuration."""
    directory = Path(config.get_str('core', 'paths', 'user_directory',
                                    default='~/.config/plapperkasten'))
    filename = config.get_str('plugins', 'spotify', 'filename_favorites',
                              default='spotify_favorites.yaml')
    return (directory.expanduser() / Path(filename).expanduser()).resolve()


class Favorites:
    """Keep a name-to-playlist mapping in an atomically replaced YAML file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        """Read favorites without replacing malformed or inaccessible files."""
        try:
            content = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return {}
        try:
            data = yaml.safe_load(content)
            if data is None:
                return {}
            if not isinstance(data, dict):
                raise ValueError('Favorites must contain playlist names and links.')
            favorites = {}
            for name, uri in data.items():
                self.validate_name(name)
                if not isinstance(uri, str):
                    raise ValueError('Each favorite needs a Spotify playlist link.')
                favorites[name] = playlist_uri(uri)
            return favorites
        except (yaml.YAMLError, UnicodeError) as error:
            raise ValueError('Could not read saved Spotify playlists.') from error

    @staticmethod
    def validate_name(name: str) -> None:
        """Require a short, single-line label, including non-ASCII names."""
        if (not isinstance(name, str) or not name.strip() or
                len(name) > 120 or any(ord(char) < 32 for char in name)):
            raise ValueError('Enter a playlist name of 1 to 120 characters.')

    def save(self, name: str, uri: str) -> None:
        """Add a favorite, replacing an existing favorite with the same name."""
        name = name.strip()
        self.validate_name(name)
        uri = playlist_uri(uri)
        favorites = self.load()
        favorites[name] = uri
        self._write(favorites)

    def remove(self, name: str) -> None:
        """Remove a known favorite without affecting playback."""
        favorites = self.load()
        if name not in favorites:
            raise ValueError('This saved playlist no longer exists.')
        del favorites[name]
        self._write(favorites)

    def _write(self, favorites: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=self.path.parent,
                    prefix=f'.{self.path.name}.', delete=False) as stream:
                temporary = Path(stream.name)
                yaml.safe_dump(favorites, stream, allow_unicode=True,
                               sort_keys=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
