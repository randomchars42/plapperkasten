#!/usr/bin/env python3
"""Use `gpiodmonitor` to monitor pins (buttons) for input (presses).
"""
import queue
import signal

from gpiodmonitor import gpiodmonitor

from plapperkasten import config as plkconfig
from plapperkasten import event as plkevent
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Inputgpiod(plugin.Plugin):
    """Monitor buttons for presses / releases.

    Attributes:
        _monitor: Instance of `gpiodmonitor.GPIODMonitor`
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """Setup pins.

        Args:
            config: The configuration.
        """

        self._monitor: gpiodmonitor.GPIODMonitor = gpiodmonitor.GPIODMonitor(
            chip_number=config.get_int('plugins', 'inputgpiod', 'chip',
                default=0),
            active_pulses=True)

        long_press_duration: int = config.get_int('plugins',
                                                  'inputgpiod',
                                                  'long_press_duration',
                                                  default=1)

        for pin in config.get_list_int('plugins',
                                       'inputgpiod',
                                       'press_short',
                                       default=[]):
            self._monitor.register(pin, on_active=self.send_short_press_signal)

        for pin in config.get_list_int('plugins',
                                       'inputgpiod',
                                       'press_long',
                                       default=[]):
            self._monitor.register_long_active(
                pin,
                callback=self.send_long_press_signal,
                seconds=long_press_duration)

    def send_short_press_signal(self, pin: int) -> None:
        """Send a raw event to signal a short press.

        Args:
            pin: The number of the pin.
        """

        self.send_to_main('raw', f'{pin}_short')

    def send_long_press_signal(self, pin: int) -> None:
        """Send a raw event to signal a long press.

        Args:
            pin: The number of the pin.
        """

        self.send_to_main('raw', f'{pin}_long')

    def run(self) -> None:
        """Check status of the gpio pins at regular intervals.

        Needs to reimplement `plugin.Plugin.run()` to use the
        contextmanager implemented by `gpiodmonitor`.
        """

        logger.debug('%s running', self.get_name())

        signal.signal(signal.SIGINT, self.on_interrupt)
        signal.signal(signal.SIGTERM, self.on_interrupt)

        self.on_before_run()

        with self._monitor.open_chip():
            while not self._terminate_signal:
                self._monitor.tick()
                try:
                    event: plkevent.Event = self._to_plugin.get(
                        True, self._monitor.check_interval / 1000)
                    if hasattr(self, 'on_' + event.name):
                        getattr(self, 'on_' + event.name)(*event.values,
                                                          **event.params)
                    else:
                        logger.error('no method for event %s defined by %s',
                                     event.name, self.get_name())
                except queue.Empty:
                    pass
                except ValueError:
                    logger.error('%s holds a closed queue', self.get_name())
        self.on_after_run()
        logger.debug('%s exited main loop', self.get_name())
