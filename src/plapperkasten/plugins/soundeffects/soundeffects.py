#!/usr/bin/env python3
"""Provide auditory feedback.
"""

import pathlib
from importlib.resources import files
import subprocess
import time

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Soundeffects(plugin.Plugin):
    """Provide auditory feedback on certain events.

    Attributes:
        _path_sounds: Path to the directory containing the sound files.
        _sounds: Dicitionary mapping events ('ready', 'shutdown', ...)
            to names of sound files.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """Register for events.

        Args:
            config: The configuration.
        """

        self.register_for('finished_loading')
        self.register_for('shutdown')
        self.register_for('error')
        self.register_for('feedback')
        self.register_for('beep')
        self._feedback_ready: float = 0
        self._feedback_process: subprocess.Popen | None = None
        self._path_sounds = pathlib.Path(
            config.get_str('plugins',
                           'soundeffects',
                           'path',
                           default=str(files(__package__).joinpath('sounds'))))
        self._sounds: dict[str, str] = config.get_dict_str_str('plugins',
                                                               'soundeffects',
                                                               'sounds',
                                                               default={})

    def on_finished_loading(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Play sound to notify the user.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event (ignored).
        """
        self.play_sound('ready')

    def on_shutdown(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Play sound to notify the user.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event (ignored).
        """
        self.play_sound('shutdown')

    def on_error(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Play sound to notify the user.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event (ignored).
        """
        self.play_sound('error')

    def on_feedback(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Play sound to notify the user.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event (ignored).
        """
        self.play_sound('feedback')

    def on_beep(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Play sound to notify the user.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event (ignored).
        """
        self.play_sound('beep')

    def play_sound(self, sound: str):
        """Play sound to notify the user.

        Args:
            sound: The name of the sound to play (must be a valid key
            in plugins.soundeffects.sounds in config.yaml).
        """
        feedback = sound in ('beep', 'feedback')
        if feedback:
            if time.monotonic() < self._feedback_ready:
                return
            if self._feedback_process is not None and self._feedback_process.poll() is None:
                return

        if not sound in self._sounds:
            logger.error('no such sound configured: "%s"', sound)
            return

        call: list[str] = [
            '/usr/bin/aplay', '-N',
            str(self._path_sounds / self._sounds[sound])
        ]
        # capture output is new and in this case required with python >= 3.7
        try:
            if feedback:
                # Keep consuming events while the sound plays; skip overlapping beeps.
                self._feedback_process = subprocess.Popen(
                    call, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.stop_feedback()
                subprocess.run(call,
                               capture_output=True,
                               encoding='utf-8',
                               check=True)
        except (OSError, subprocess.CalledProcessError):
            logger.error('could not play sound "%s"', sound)
        self._feedback_ready = time.monotonic() + 0.1

    def stop_feedback(self) -> None:
        """Reap feedback playback before a priority sound or shutdown."""
        if self._feedback_process is not None:
            if self._feedback_process.poll() is None:
                self._feedback_process.terminate()
            self._feedback_process.wait()
            self._feedback_process = None

    def on_after_run(self) -> None:
        self.stop_feedback()
