"""Control a local Spotify Soloist service with the existing player events."""

import json
import re
import subprocess
import time
from typing import Any

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging
from plapperkasten.spotify_sources import playable_uri

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
        self._queue_interval = max(2.0, config.get_float(
            'plugins', 'spotify', 'interval_queue', default=10))
        self._queue_limit = min(5000, max(1, config.get_int(
            'plugins', 'spotify', 'queue_limit', default=1000)))
        self._next_queue_poll = 0.0
        self._queue_key = ('', '')
        self._last_queue = ''
        self._shared_volume = config.get_bool(
            'plugins', 'spotify', 'shared_volume', default=False)
        self._volume_max = min(100, max(0, config.get_int(
            'plugins', 'soundpwwp', 'max', default=100)))
        self._last_output_volume: int | None = None
        self._last_player_volume: int | None = None
        self._pending_volume: int | None = None
        self._volume_deadline = 0.0
        if self._shared_volume:
            self.register_for('volume_max')
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

    def _pipewire(self, *arguments: str) -> str:
        try:
            return subprocess.run(
                ['wpctl', *arguments], capture_output=True, text=True,
                check=True, timeout=self._timeout).stdout
        except (OSError, subprocess.SubprocessError) as error:
            raise SoloistError('Shared volume control is unavailable.') from error

    def _set_player_volume(self, target: int, current: int) -> None:
        if target == current:
            self._pending_volume = None
            return
        self._command('volume', str(target))
        self._pending_volume = target
        self._volume_deadline = time.monotonic() + 3

    def _sync_volume(self, snapshot: dict[str, Any]) -> None:
        """Use the output mixer for both sources; ignore delayed CLI echoes.

        Soloist's PipeWire stream must be locked at unity gain so its reported
        volume is a control value rather than another stage of attenuation.
        """
        player = snapshot.get('volume')
        if isinstance(player, bool) or not isinstance(player, int) or not 0 <= player <= 100:
            raise SoloistError('Spotify returned an invalid volume.')
        output = re.match(r'Volume: ([0-9.]+)', self._pipewire(
            'get-volume', '@DEFAULT_AUDIO_SINK@'))
        if output is None:
            raise SoloistError('Shared volume control is unavailable.')
        master = round(float(output.group(1)) * 100)
        target = min(self._volume_max, max(0, master))
        if (master != self._last_output_volume or not snapshot['is_active'] or
                target != master):
            # The box wins on startup and whenever its controls change.
            if target != master:
                self._pipewire('set-volume', '@DEFAULT_AUDIO_SINK@', f'{target}%')
            self._set_player_volume(target, player)
        elif self._pending_volume is not None and player != self._pending_volume:
            if time.monotonic() < self._volume_deadline:
                return
            if player == self._last_player_volume:
                self._set_player_volume(self._pending_volume, player)
                return
            # A fresh phone change can supersede an unconfirmed command.
            self._pending_volume = None
            target = min(self._volume_max, player)
            if target != master:
                self._pipewire('set-volume', '@DEFAULT_AUDIO_SINK@', f'{target}%')
            self._set_player_volume(target, player)
        elif player != self._last_player_volume:
            # Includes a confirmed echo, which needs no mixer write.
            target = min(self._volume_max, player)
            if target != master:
                self._pipewire('set-volume', '@DEFAULT_AUDIO_SINK@', f'{target}%')
            self._set_player_volume(target, player)
        self._last_output_volume = target
        self._last_player_volume = player

    def on_volume_max(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        try:
            self._volume_max = min(100, max(0, int(values[0])))
        except (IndexError, ValueError):
            return

    def _failed(self, error: Exception) -> None:
        self._device_active = False
        self._last_output_volume = self._last_player_volume = None
        self._pending_volume = None
        self.send_idle()
        self._publish_queue({'previous': [], 'current': None, 'upcoming': [],
                             'context': '', 'error': 'Spotify queue unavailable.'})
        self._next_queue_poll = 0
        self._report('Unavailable', error=str(error))

    def _publish_queue(self, data: dict[str, Any]) -> None:
        serialized = json.dumps(data)
        if serialized != self._last_queue:
            self.send_to_main('spotify_queue', data=serialized)
            self._last_queue = serialized

    @staticmethod
    def _queue_item(entity: Any) -> dict[str, str] | None:
        """Keep only display text and playable URIs from Soloist entities."""
        if not isinstance(entity, dict):
            return None
        decorations = entity.get('decorations') or {}
        if not isinstance(decorations, dict):
            return None
        identity = decorations.get('identity') or {}
        name = str(identity.get('name') or '') if isinstance(identity, dict) else ''
        uri = str(entity.get('uri') or '')
        if not name and not uri:
            return None
        artists = []
        for creator in decorations.get('creators') or []:
            if not isinstance(creator, dict):
                continue
            artist = creator.get('entity') or {}
            try:
                artist_name = artist['decorations']['identity']['name']
            except (KeyError, TypeError):
                continue
            if isinstance(artist_name, str):
                artists.append(artist_name)
        return {'name': name or uri, 'artist': ', '.join(artists), 'uri': uri}

    def _poll_queue(self, snapshot: dict[str, Any]) -> None:
        now = time.monotonic()
        context = snapshot.get('context') or {}
        current = self._queue_item(snapshot.get('item'))
        key = (str(context.get('uri') or ''), current['uri'] if current else '')
        if now < self._next_queue_poll and key == self._queue_key:
            return
        self._next_queue_poll = now + self._queue_interval
        self._queue_key = key
        payload: dict[str, Any] = {
            'previous': [], 'current': current, 'upcoming': [],
            'context': '', 'error': '', 'limit': self._queue_limit,
        }
        try:
            payload['context'] = str(context.get('decorations', {}).get(
                'identity', {}).get('name') or '')
            queue = json.loads(self._command('queue', str(self._queue_limit), '--json'))
            if not isinstance(queue, dict):
                raise ValueError('Invalid queue.')
            for group in ('previous', 'upcoming'):
                entries = queue.get(group)
                if not isinstance(entries, list):
                    raise ValueError('Invalid queue entries.')
                for entry in entries:
                    item = self._queue_item(entry.get('item') if isinstance(entry, dict) else None)
                    if item is not None:
                        payload[group].append(item)
        except (SoloistError, ValueError, TypeError, AttributeError):
            payload.update(previous=[], upcoming=[], error='Spotify queue unavailable. Retrying…')
        self._publish_queue(payload)

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
            volume_error = ''
            if self._shared_volume:
                try:
                    self._sync_volume(snapshot)
                except SoloistError as error:
                    volume_error = str(error)
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
            self._poll_queue(snapshot)
            self._report(self._state.capitalize() if self._device_active
                         else 'Ready', self._track if self._device_active else '',
                         volume_error)
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
            uri = playable_uri(params.get('key', ''))
            self._active = True
            self._command('activate')
            self._command('play', uri)
            self._next_queue_poll = 0
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
            self._next_queue_poll = 0
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
