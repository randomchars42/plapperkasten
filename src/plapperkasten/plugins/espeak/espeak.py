#!/usr/bin/env python3
"""Provide spoken messages via espeak(-ng).
"""

import datetime
import locale
import pkg_resources
import subprocess

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Espeak(plugin.Plugin):
    """Provide speech output via espeak(-ng).

    Attributes:
        _amplitude: The amplitude to use.
        _app: Use `espeak` or `espeak-ng`
        _format_day: How to output the day.
        _format_date: How to output the date.
        _format_locale: Locale for `strftime()`.
        _format_time: How to output the time.
        _pitch: The pith to use.
        _voice: The voice to use.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """Register for events.

        Args:
            config: The configuration.
        """

        self.register_for('say')
        self.register_for('say_date')
        self.register_for('say_day')
        self.register_for('say_time')
        self._amplitude = config.get_str('plugins',
                                         'espeak',
                                         'amplitude',
                                         default='200')
        self._app = config.get_str('plugins',
                                   'espeak',
                                   'app',
                                   default='espeak-ng')
        self._format_date = config.get_str('plugins',
                                           'espeak',
                                           'format-date',
                                           default='Today is %B %d, %Y')
        self._format_day = config.get_str('plugins',
                                          'espeak',
                                          'format-day',
                                          default='Today is %A')
        self._format_locale = config.get_str('plugins',
                                             'espeak',
                                             'format-locale',
                                             default='en_Us')
        self._format_time = config.get_str('plugins',
                                           'espeak',
                                           'format-time',
                                           default='It is %H:%M')
        self._pitch = config.get_str('plugins',
                                     'espeak',
                                     'pitch',
                                     default='50')
        self._voice = config.get_str('plugins',
                                     'espeak',
                                     'voice',
                                     default='en')
        locale.setlocale(locale.LC_TIME, self._format_locale)

    def on_say(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Say the given text.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event: output `text`
        """
        if 'text' in params:
            self.say(params['text'])
        else:
            logger.error('should say something, but no text given')

    def on_say_date(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Say the date.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event (ignored).
        """
        self.say(datetime.datetime.now().strftime(self._format_date))

    def on_say_day(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Say the day.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event (ignored).
        """
        self.say(datetime.datetime.now().strftime(self._format_day))

    def on_say_time(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Say the date.

        Args:
            *values: Values attached to the event (ignored).
            **params: Parameters attached to the event (ignored).
        """
        self.say(datetime.datetime.now().strftime(self._format_time))

    def say(self, text: str):
        """Say something.

        Ask other plugins to pause beforehand and resume afterwards.

        Args:
            text: The text to output.
        """

        # kindly ask other plugins to pause
        self.send_to_main('pause')

        call: list[str] = [
            f'/usr/bin/{self._app}', f'-v{self._voice}', f'-a{self._amplitude}',
            f'-p{self._pitch}', text]

        # capture output is new and in this case required with python >= 3.7
        try:
            subprocess.run(call,
                           capture_output=True,
                           encoding='utf-8',
                           check=True)
        except subprocess.CalledProcessError:
            logger.error('could not say "%s"', text)

        # kindly ask other plugins to resume
        self.send_to_main('resume')
