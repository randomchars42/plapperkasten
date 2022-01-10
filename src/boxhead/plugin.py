#!/usr/bin/env python3
"""Base plugin."""

import logging
import multiprocessing
import queue
import signal

from boxhead import boxhead

logger = logging.getLogger(__name__)


class Plugin(multiprocessing.Process):
    """Base class for plugins using their own process.

    Attributes:
        _name: The name of the plugin that subclasses this class.
        _tick_interval: The interval with wich `on_tick()` will be
            called.
        _terminate_signal: Terminates the process if `True`.
        _to_plugin: Queue to recieve signals from the main process.
        _from_plugin: Queue to send signals to the main process.
        _logger: Logger for records, configured to queue records to
            the main process.
    """

    def __init__(self, name: str, main: boxhead.BoxHead,
                 to_plugin: multiprocessing.Queue,
                 from_plugin: multiprocessing.Queue) -> None:
        """Initialises the plugin and then calls `on_init()`.

        All parameters which are passed in by reference may not be
        stored in this object to avoid concurrent access by different entities
        to the same resource.

        There should be no need to overwrite this function as it calls
        `on_init()` which may more easily be overwriten by subclasses.

        Args:
            name: The name of this plugin as its known to the main
                process.
            main: The instance of the central module.
            to_plugin: Queue providing events for the plugins.
            from_plugin: Queue to get messages to the main process.
        """

        multiprocessing.Process.__init__(self)
        self._name: str = name
        self._tick_interval: int = 1
        self._terminate_signal: bool = False
        self._to_plugin: multiprocessing.Queue = to_plugin
        self._from_plugin: multiprocessing.Queue = from_plugin

        self._logger = logging.getLogger(name)

        self.on_init(main)
        self._logger.debug('initialised %s', self.get_name())

    def get_name(self) -> str:
        """Returns the name set by `__init__()`.

        Returns:
            A string with the name set by BoxHead.
        """

        return self._name

    def on_init(self, main: boxhead.BoxHead) -> None:
        """Initialises class members.

        May be overwritten by subclasses to do something more useful.

        Args:
            main: The instance of the central module.
        """

        self._logger.debug('initialising %s', self.get_name())

    def on_terminate(self) -> None:
        """Ends execution of the process after a `terminate` event."""

        self._terminate_signal = True

    def on_tick(self) -> None:
        """The place to do your work.

        Gets called in regulare intervals detemined by
        `_tick_interval`.
        """

        self._logger.debug('%s working', self.get_name())

    def on_interrupt(self, signal_num: int, frame: object) -> None:
        #pylint: disable=unused-argument
        """Stop the running process on interrupt.

        Args:
            signal_num: The signal number that was sent to the process.
            frame: The current stack frame.
        """

        self._terminate_signal = True

    def run(self) -> None:
        self._logger.debug('%s running', self.get_name())

        signal.signal(signal.SIGINT, self.on_interrupt)
        signal.signal(signal.SIGTERM, self.on_interrupt)

        while not self._terminate_signal:
            self.on_tick()
            try:
                event: object = self._to_plugin.get(True, self._tick_interval)
                if hasattr(self, 'on_' + event):
                    getattr(self, 'on_' + event)()
                else:
                    self._logger.error('no method for event %s defined by %s',
                                       event, self.get_name())
            except queue.Empty:
                pass
            except ValueError:
                self._logger.error('%s holds a closed queue', self.get_name())

    def __del__(self) -> None:
        """Tidies up afterwards."""

        self._logger.debug('%s is stopping', self.get_name())
