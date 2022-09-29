#!/usr/bin/env python3
"""A plugin controlling ALSA volume.
"""

import pathlib
import re
import subprocess

from typing import Optional

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Soundalsa(plugin.Plugin):
    """Plugin controlling the sound via ALSA.

    Attributes:
        _volume_max: The maximal volume.
        _volume_step: The step by which to increase / decrease the volume.
        _volume_current: The current volume.
        _card: Index of the soundcard to use (may be changed dynamically).
        _controls: Mapping which control to expect for which card.
        _profiles: Dictionary of ALSA profiles. Each profile name (key)
            is associated with a path to a file which may serve as an
            `~/.asoundrc`-file. An empty path means no file.
        _default_profile: The key of the default profile.
        _current_profile: The key of the current profile.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """This gets called by the constructor.

        Args:
            config: The configuration.
        """

        self._volume_max: int = config.get_int('plugins',
                                                  'soundalsa',
                                                  'max',
                                                  default=100)
        self._volume_step: int = config.get_int('plugins',
                                                  'soundalsa',
                                                  'step',
                                                  default=1)
        self._card: int = config.get_int('plugins',
                                                  'soundalsa',
                                                  'default_card',
                                                  default=0)
        self._controls: dict[int, str] = config.get_dict_int_str('plugins',
                                                  'soundalsa',
                                                  'controls',
                                                  default=dict({0: 'Master'}))
        self._profiles: dict[str, str] = config.get_dict_str_str('plugins',
                                                  'soundalsa',
                                                  'profiles',
                                                  default=dict({'default': ''}))
        self._default_profile: str = config.get_str('plugins',
                                                  'soundalsa',
                                                  'default_profile',
                                                  default='default')
        self._current_profile: str = self._default_profile
        self._volume_current: int = 0

        self.register_for('volume_decrease')
        self.register_for('volume_increase')
        self.register_for('volume_max')
        self.register_for('toggle_alsa_profile')

    def on_before_run(self) -> None:
        """Get current volume and set maximal volume.

        Do not do this in `on_init` as then the subprocess is not yet
        running and the object has to be copied into the process and
        havoc ensues in tidying up.
        """
        self.set_max_volume(self._volume_max)
        self.toggle_profile(self._default_profile)
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
        self._volume_max = volume
        if self._volume_current > volume:
            self.set_volume(volume)

    def amixer(self, *args: str) -> str:
        """Call amixer as a subprocess and return its output.

        Args:
            *args: One string for each parameter part passed to `amixer`.

        Returns:
            The output from the call to amixer.
        """
        call: list[str] = ['amixer']

        if len(args) > 0:
            call += args

        logger.debug('calling amixer: %s', ','.join(list(call)))

        try:
            result: subprocess.CompletedProcess = subprocess.run(call,
                    capture_output=True, encoding='utf-8', check=True)
        except subprocess.CalledProcessError as e:
            logger.error('error calling amixer: "%s"', e.stderr)
            return ''

        return result.stdout

    def get_control(self) -> str:
        """Get the currently active control.

        Returns:
            The control for use in ALSA / amixer.
        """
        try:
            return self._controls[self._card]
        except IndexError:
            return 'Master'

    def query_volume(self) -> int:
        """ Retrieve the current volume from ALSA.

        Returns:
            The volume.
        """
        raw: list[str] = self.amixer('get', self.get_control()).split('\n')
        # if Master is stereo this will only capture the left line and we infer
        # that this also holds true for the right line
        result: Optional[re.Match] = re.match(re.compile(
            r'\s+[a-zA-Z :]+\s+[0-9]+\s*\[(?P<volume>[0-9]+)%\]'),
            raw[5])
        if not result is None:
            volume: int = int(result.groupdict()['volume'])
        else:
            volume = self._volume_max
        logger.debug('current volume: %s', str(volume))
        return volume

    def set_volume(self, volume: int):
        """Set an absolute value for the volume.

        Args:
            volume:  An integer between 0 and 100.
        """
        result: str = ''
        if volume >= self._volume_max:
            logger.debug('max volume reached (%s)', str(self._volume_max))
            result = self.amixer('set', self.get_control(),
                    f'{str(self._volume_max)}%')
        elif volume <= 0:
            logger.debug('min volume reached')
            result = self.amixer('set', self.get_control(), '0%')
        else:
            logger.debug('setting volume to %s', str(volume))
            result = self.amixer('set', self.get_control(), f'{str(volume)}%')

        if result == '':
            logger.error('could not change volume')

        self._volume_current = self.query_volume()

    def change_volume(self, direction: str, step: Optional[int] = None):
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
            step = self._volume_step

        volume = self.query_volume()

        if direction == '-' and volume - step <= 0:
            logger.debug('min volume reached')
            result = self.amixer('set', self.get_control(), '0%')
        elif direction == '+' and volume + step >= self._volume_max:
            logger.debug('max volume reached (%s)', str(self._volume_max))
            result = self.amixer('set', self.get_control(),
                    f'{str(self._volume_max)}%')
        else:
            logger.debug('volume: %s%s', str(direction), str(step))
            result = self.amixer('set', self.get_control(),
                    f'{str(step)}%{direction}')

        if result == '':
            logger.error('could not change volume')

        self._volume_current = self.query_volume()
        self.send_to_main('feedback')

    def on_toggle_alsa_profile(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Toggles the ALSA profile.

        Args:
            values: Values attached to the event. Takes the first value as the
                profile to toggle.
            params: Parameters attached to the event (ignored).
        """
        try:
            if not values[0] in self._profiles.keys():
                logger.error('profile "%s" not defined', values[0])
            self.toggle_profile(values[0])
        except IndexError:
            logger.error('no profile specified')

    def toggle_profile(self, profile: str):
        """Toggle between the default profile and the given profile.

        Args:
            profile: The profile to toggle.
        """
        logger.debug('toggling profile "%s"', profile)

        # profile currently active so switch to default profile
        if profile == self._current_profile:
            logger.debug('profile "%s" already active, switching to default',
                    profile)
            profile = self._default_profile

        self.activate_profile(profile)

    def activate_profile(self, profile: str):
        """Activate the profile by linking `~/.asoundrc`.

        Args:
            profile: The profile to activate.
        """
        logger.debug('activating profile "%s"', profile)

        try:
            profile_path: pathlib.Path = pathlib.Path(self._profiles[profile])
            target_path: pathlib.Path = pathlib.Path('~/.asoundrc').expanduser()

            if not profile_path.exists():
                logger.error('profile "%s" does not exist', profile)
                return

            # make a backup if an actual `~/.asoundrc` existis and not just a
            # symlink we created
            if target_path.exists() and not target_path.is_symlink():
                target_path.rename('~/.asoundrc.bk')

            if target_path.exists() or target_path.is_symlink():
                target_path.unlink()

            if not self._profiles[profile] == '':
                target_path.symlink_to(profile_path)
        except OSError as e:
            logger.error('could not activate profile ("%s")', str(e))
        except KeyError:
            logger.error('invalid profile name "%s"', profile)

        try:
            subprocess.run(['alsactl', 'restore'],
                    capture_output=True, encoding='utf-8', check=True)
        except subprocess.CalledProcessError as e:
            logger.error('error calling alsactl: "%s"', e.stderr)
            return

        logger.debug('profile "%s" activated', profile)
