#!/usr/bin/env python3
"""A plugin controlling ALSA volume.
"""

import json
import re
import subprocess

from typing import Optional, Any

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Soundpwwp(plugin.Plugin):
    """Plugin controlling the sound via Pipewire / Wireplumber.

    Attributes:
        _max_volume: The maximal volume.
        _step: The step by which to increase / decrease the volume.
        _volume_current: The current volume.
        _default_sink: The sink to select at startup ('node.name')
        _sink_ids: Mapping between sink name ('node.name' in Pipewire) and its
            (dynamic) ID which is needed to control the volume or reroute the
            audio sink.
        _current_sink_id: The id of the current sink.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """This gets called by the constructor.

        Args:
            config: The configuration.
        """

        self._max_volume: int = config.get_int('plugins',
                                                  'soundpwwp',
                                                  'max',
                                                  default=100)
        self._step: int = config.get_int('plugins',
                                                  'soundpwwp',
                                                  'step',
                                                  default=1)
        self._default_sink: str = config.get_str('plugins',
                                                  'soundpwwp',
                                                  'default_sink',
                                                  default='default')
        self._sink_ids: dict[str, str] = dict(
                {'default': '@DEFAULT_AUDIO_SINK@'})
        self._current_sink_id: str = '@DEFAULT_AUDIO_SINK@'
        self._current_volume: int = 0

        self.register_for('volume_decrease')
        self.register_for('volume_increase')
        self.register_for('volume_max')
        self.register_for('toggle_pwwp_sink')

    def on_before_run(self) -> None:
        """Get current volume and set maximal volume.

        Do not do this in `on_init` as then the subprocess is not yet
        running and the object has to be copied into the process and
        havoc ensues in tidying up.
        """
        self.query_sinks()
        self.query_current_sink()
        self.set_max_volume(self._max_volume)
        self.toggle_sink(self._default_sink)
        logger.debug('current volume: %s', str(self.query_volume()))

    def on_volume_increase(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Increase the volume by `_volume_step`.

        Args:
            values: Values attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """
        self.change_volume('+')

    def on_volume_decrease(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Decrease the volume by `_volume_step`.

        Args:
            values: Values attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """
        self.change_volume('-')

    def on_volume_max(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Jumps to the previous title.

        Args:
            values: Values attached to the event. Takes the first value and
                tries to convert it into an integer. This will become the new
                maximal volume.
            params: Parameters attached to the event (ignored).
        """
        try:
            self.set_max_volume(int(values[0]))
        except KeyError:
            logger.error('cannot set maximal volume, no volume provided')
        except ValueError:
            logger.error('cannot set maximal volume, invalid value ("%s")',
                    str(values[0]))

    def set_max_volume(self, volume: int) -> None:
        """Set the maximal volume after basic sanity checks.

        Args:
            volume: The new maximal volume [%].
        """
        if volume > 100:
            volume = 100
        elif volume < 0:
            volume = 0
        logger.debug('setting max volume to %s', str(volume))
        self._max_volume = volume
        if self._current_volume > volume:
            self.set_volume(volume)

    def wpctl(self, *args: str) -> str:
        """Call wpctl as a subprocess and return its output.

        Args:
            *args: One string for each parameter part passed to `amixer`.

        Returns:
            The output from the call to amixer.
        """
        call: list[str] = ['wpctl']

        if len(args) > 0:
            call += args

        logger.debug('calling wpctl: %s', ','.join(list(call)))

        try:
            result: subprocess.CompletedProcess = subprocess.run(call,
                    capture_output=True, encoding='utf-8', check=True)
        except subprocess.CalledProcessError as e:
            logger.error('error calling wpctl: "%s"', e.stderr)
            return ''

        return result.stdout

    def query_volume(self) -> int:
        """ Retrieve the current volume from Wireplumber.

        Returns:
            The volume.
        """
        raw: str = self.wpctl('get-volume', '@DEFAULT_AUDIO_SINK@').split(
                '\n')[0]
        result: Optional[re.Match] = re.match(re.compile(
            r'Volume: (?P<volume>[0-9.]+)'), raw)
        if not result is None:
            # at the moment, wpctl is incoherrent as it takes volume in % but
            # gives it in fractions
            volume: int = int(float(result.groupdict()['volume']) * 100)
        else:
            volume = self._max_volume
        logger.debug('current volume: %s', str(volume))
        return volume

    def set_volume(self, volume: int) -> None:
        """Set an absolute value for the volume.

        Args:
            volume:  An integer between 0 and 100.
        """
        result: str = ''
        if volume >= self._max_volume:
            logger.debug('max volume reached (%s)', str(self._max_volume))
            result = self.wpctl('set-volume', '@DEFAULT_AUDIO_SINK@',
                    f'{str(self._max_volume)}%')
        elif volume <= 0:
            logger.debug('min volume reached')
            result = self.wpctl('set-volume', '@DEFAULT_AUDIO_SINK@', '0%')
        else:
            logger.debug('setting volume to %s', str(volume))
            result = self.wpctl('set-volume', '@DEFAULT_AUDIO_SINK@',
                    f'{str(volume)}%')

        if result == '':
            logger.error('could not change volume')

        self._volume_current = self.query_volume()

    def change_volume(self, direction: str, step: Optional[int] = None) -> None:
        """Increment / decrement the volume.

        Args:
            direction: Increment ["+"] or decrement ["-"].
            step: Change by how much [% of total].
        """
        # increase / decrease volume in steps of X %
        if not direction in ['+', '-']:
            logger.error('no such direction "%s"', direction)
            return

        if step is None:
            step = self._step

        volume = self.query_volume()

        if direction == '-' and volume - step <= 0:
            logger.debug('min volume reached')
            result = self.wpctl('set-volume', '@DEFAULT_AUDIO_SINK@', '0%')
        elif direction == '+' and volume + step >= self._max_volume:
            logger.debug('max volume reached (%s)', str(self._max_volume))
            result = self.wpctl('set-volume', '@DEFAULT_AUDIO_SINK@',
                    f'{str(self._max_volume)}%')
        else:
            logger.debug('volume: %s%s', str(direction), str(step))
            result = self.wpctl('set-volume', '@DEFAULT_AUDIO_SINK@',
                    f'{str(step)}%{direction}')

        if result == '':
            logger.error('could not change volume')

        self._volume_current = self.query_volume()
        self.send_to_main('beep')

    def on_toggle_pwwp_sink(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Toggles the Pipewire sink.

        Args:
            values: Values attached to the event. Takes the first value as the
                sink to toggle.
            params: Parameters attached to the event (ignored).
        """
        try:
            if not values[0] in self._sink_ids:
                logger.error('sink "%s" not defined', values[0])
            self.toggle_sink(values[0])
        except IndexError:
            logger.error('no sink specified')

    def toggle_sink(self, sink: str) -> None:
        """Toggle between the default sink and the given sink.

        Args:
            sink: The name (`node.name`) of the sink to toggle.
        """

        try:
            sink_id: str = self._sink_ids[sink]
            logger.debug('toggling sink "%s" (%s)', sink, sink_id)
        except KeyError:
            logger.error('no such sink "%s"', sink)
            return

        # profile currently active so switch to default profile
        if sink_id == self._current_sink_id:
            logger.debug('sink "%s" (%s) already active, switching to default',
                    sink, sink_id)
            sink_id = self._sink_ids[self._default_sink]
        else:
            logger.debug('switching to sink "%s" (%s)',
                    sink, sink_id)

        self.wpctl('set-default', sink_id)
        self.query_current_sink()

    def query_sinks(self) -> None:
        """Query available sinks and card names."""

        try:
            pw_dump: list[Any] = json.loads(subprocess.check_output('pw-dump'))
            filtered: list[Any] = [item for item in pw_dump if (
                item['type'] == 'PipeWire:Interface:Node' and
                'alsa.card_name' in item['info']['props'].keys())]
            for sink in filtered:
                self._sink_ids[sink['info']['props']['node.name']] = str(
                        sink['id'])
                logger.debug('found sink "%s" with id "%s" on card "%s"',
                        sink['info']['props']['node.name'], sink['id'],
                        sink['info']['props']['alsa.card_name'])
        except subprocess.CalledProcessError as e:
            logger.error('error calling pw-dump: "%s"', e.stderr)
            return

    def query_current_sink(self) -> None:
        """Get the id of the currently used audio sink."""

        raw: str = self.wpctl('inspect', '@DEFAULT_AUDIO_SINK@').split('\n')[0]
        result: Optional[re.Match] = re.match(re.compile(
            r'id (?P<id>[0-9]+)'),
            raw)
        if not result is None:
            sink_id: str = result.groupdict()['id']
        else:
            sink_id = '@DEFAULT_AUDIO_SINK@'
        self._current_sink_id = sink_id
        logger.debug('current sink: %s', sink_id)
