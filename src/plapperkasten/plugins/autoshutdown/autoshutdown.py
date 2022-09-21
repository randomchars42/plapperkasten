#!/usr/bin/env python3
"""Initiate shutdown after all process declared themselves idle.
"""

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Autoshutdown(plugin.Plugin):
    """Initiate shutdown after all process declared themselves idle.

    Attributes:
        _idle_time: The time to wait after all plugins said they are
            idle until the initiation of shutdown.
        _countdown: The countdown.
        _global_idle_state: The global idle state.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """Get configured idle time before shutdown.

        Args:
            config: The configuration.
        """
        self._idle_time: int = config.get_int('plugins',
                                              'autoshutdown',
                                              'idle_time',
                                              default=300)
        self._countdown: int = self._idle_time
        self._global_idle_state: bool = False
        # set the frequence of calls to `on_tick` to 1 / s
        self._tick_interval: int = 1

        self.register_for('idle')
        self.register_for('busy')

    def on_idle(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Starts a countdown until shutdown.

        Args:
            values: Values that are attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """
        self._global_idle_state = True
        logger.debug('beginning countdown')

    def on_busy(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Stops the countdown.

        Args:
            values: Values that are attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """
        self._global_idle_state = False
        self._countdown = self._idle_time

    def on_tick(self) -> None:
        """Decreases the shutdown if all processes declared to be idle.

        Gets called once per second.
        """
        if self._global_idle_state:
            logger.debug(f'seconds until shutdown: {self._countdown}')
            self._countdown -= self._tick_interval
            if self._countdown <= 0:
                self.send_to_main('shutdown')
