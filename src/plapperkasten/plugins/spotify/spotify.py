"""Control a local Spotify Soloist service with the existing player events."""

import json
import subprocess
from typing import Any

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging
from plapperkasten.spotify_sources import playlist_uri

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class SoloistError(Exception):
    """A local Soloist command failed or returned invalid playback state."""


class Spotify(plugin.Plugin):
    """Translate Plapperkasten events into bounded local CLI commands.

    Soloist owns pairing, credentials, streaming and audio output. This plugin
    only controls its local endpoint and never needs the Spotify API key.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        self._enabled = config.get_bool('plugins', 'spotify', 'enabled',
                                        default=False)
        self._executable = config.get_str('plugins', 'spotify', 'executable',
                                          default='soloist')
        self._endpoint = config.get_str('plugins', 'spotify', 'endpoint',
                                        default='127.0.0.1:9090')
        self._timeout = max(0.1, config.get_float(
            'plugins', 'spotify', 'command_timeout', default=3))
        self._tick_interval = max(1.0, config.get_float(
            'plugins', 'spotify', 'interval_poll', default=2))
        self._active = False
        self._device_active = False
        self._state = 'idle'
        self._track = ''
        self._last_report: tuple[str, str, str] | None = None
        for event in ('load_source', 'play', 'pause', 'resume', 'toggle',
                      'stop', 'next', 'previous'):
            self.register_for(event)

    def _command(self, *arguments: str) -> str:
        """Run a CLI command without a shell, with a finite deadline."""
        try:
            result = subprocess.run(
                [self._executable, 'ctl', *arguments, '--ws', self._endpoint],
                capture_output=True, text=True, check=True,
                timeout=self._timeout)
            return result.stdout
        except FileNotFoundError as error:
            raise SoloistError('Spotify Soloist is not installed.') from error
        except subprocess.TimeoutExpired as error:
            raise SoloistError('Spotify Soloist did not respond in time.') from error
        except (OSError, subprocess.CalledProcessError) as error:
            raise SoloistError(
                'Spotify is unavailable. Check that Soloist is running and paired.') from error

    def _report(self, state: str, track: str = '', error: str = '') -> None:
        report = (state, track, error)
        if report != self._last_report:
            if error:
                logger.warning('%s', error)
            self.send_to_main('spotify_status', state=state, track=track,
                              error=error)
            self._last_report = report

    def _failed(self, error: Exception) -> None:
        self._device_active = False
        self.send_idle()
        self._report('Unavailable', error=str(error))

    def _snapshot(self) -> dict[str, Any]:
        try:
            snapshot = json.loads(self._command('now', '--json'))
            if (not isinstance(snapshot, dict) or
                    snapshot.get('status') not in
                    ('idle', 'playing', 'paused', 'buffering') or
                    not isinstance(snapshot.get('is_active'), bool)):
                raise ValueError('Invalid playback state.')
            return snapshot
        except (ValueError, TypeError) as error:
            raise SoloistError('Spotify returned an invalid playback status.') from error

    def on_before_run(self) -> None:
        self.on_tick()

    def on_tick(self) -> None:
        if not self._enabled:
            return
        try:
            snapshot = self._snapshot()
            self._state = snapshot['status']
            self._device_active = snapshot['is_active']
            item = snapshot.get('item') or {}
            identity = (item.get('decorations') or {}).get('identity') or {}
            self._track = str(identity.get('name') or '')
            if self._active and self._device_active and self._state in (
                    'playing', 'buffering'):
                self.send_busy()
            else:
                self.send_idle()
            self._report(self._state.capitalize() if self._device_active
                         else 'Ready', self._track if self._device_active else '')
        except (SoloistError, AttributeError) as error:
            self._failed(SoloistError('Spotify returned an invalid playback status.')
                         if isinstance(error, AttributeError) else error)

    def on_load_source(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        if not self._enabled:
            return
        if params.get('use') != self.get_name():
            if self._active:
                # Clear ownership before polling so delayed Soloist updates
                # cannot take over controls after another source was selected.
                self._active = False
                try:
                    if self._snapshot()['is_active']:
                        self._command('pause')
                except SoloistError as error:
                    self._failed(error)
                self.send_idle()
            return
        try:
            uri = playlist_uri(params.get('key', ''))
            self._active = True
            self._command('activate')
            self._command('play', uri)
            self.send_busy()
            self._report('Starting playback')
        except (ValueError, SoloistError) as error:
            self._failed(error)

    def _control(self, command: str, *arguments: str) -> None:
        if not self._enabled or not self._active:
            return
        try:
            if command == 'play':
                self._command('activate')
            elif not self._snapshot()['is_active']:
                # A phone may have transferred Spotify to another speaker.
                return
            self._command(command, *arguments)
            if command == 'play':
                self.send_busy()
            # CLI success means dispatched, not confirmed; on_tick reports
            # only the playback state subsequently confirmed by Soloist.
        except SoloistError as error:
            self._failed(error)

    def on_play(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        self._control('play')

    def on_resume(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        self._control('play')

    def on_pause(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        self._control('pause')

    def on_toggle(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        if not self._enabled or not self._active:
            return
        try:
            snapshot = self._snapshot()
            self._control('pause' if snapshot['is_active'] and
                          snapshot['status'] in ('playing', 'buffering')
                          else 'play')
        except SoloistError as error:
            self._failed(error)

    def on_stop(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        if not self._enabled or not self._active:
            return
        try:
            if self._snapshot()['is_active']:
                self._command('pause')
                self._command('seek', '0')
        except SoloistError as error:
            self._failed(error)

    def on_next(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        self._control('next')

    def on_previous(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        self._control('prev')

    def on_after_run(self) -> None:
        if self._enabled and self._active:
            self._control('pause')
        self.send_idle()
