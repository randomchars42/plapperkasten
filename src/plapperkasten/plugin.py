#!/usr/bin/env python3
"""Base plugin."""

import multiprocessing
import queue
import signal

from plapperkasten import config as plkconfig
from plapperkasten import event as plkevent
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Plugin(multiprocessing.Process):
    """Base class for plugins using their own process.

    Attributes:
        _name: The name of the plugin that subclasses this class.
        _tick_interval: The interval with wich `on_tick()` will be
            called in seconds.
        _terminate_signal: Terminates the process if `True`.
        _to_plugin: Queue to recieve signals from the main process.
        _from_plugin: Queue to send signals to the main process.
        _registered_events: A list of events the plugin wants to be
            registered for.
        _busy: Indicator if the plugin has marked itself as busy.
    """

    def __init__(self, name: str, config: plkconfig.Config,
                 to_plugin: multiprocessing.Queue,
                 from_plugin: multiprocessing.Queue) -> None:
        """Initialises the plugin and then calls `on_init()`.

        All parameters which are passed in by reference may not be
        stored in this object to avoid concurrent access by different
        entities to the same resource.

        There should be no need to overwrite this function as it calls
        `on_init()` which may more easily be overwriten by subclasses.

        Args:
            name: The name of this plugin as its known to the main
                process.
            config: The configuration. Do not store it as it is not
                multiprocessing safe.
            to_plugin: Queue providing events for the plugins.
            from_plugin: Queue to get messages to the main process.
        """

        multiprocessing.Process.__init__(self)
        self._name: str = name
        self._tick_interval: float = 1
        self._terminate_signal: bool = False
        self._to_plugin: multiprocessing.Queue = to_plugin
        self._from_plugin: multiprocessing.Queue = from_plugin
        self._registered_events: list[str] = []
        self._busy: bool = False

        self.on_init(config)
        logger.debug('initialised %s', self.get_name())

    def get_name(self) -> str:
        """Returns the name set by `__init__()`.

        Returns:
            A string with the name set by Plapperkasten.
        """

        return self._name

    def on_init(self, config: plkconfig.Config) -> None:
        # pylint: disable=unused-argument
        """Initialises class members.

        May be overwritten by subclasses to do something more useful.

        Args:
            config: The configuration. Do not store it as it is not
                multiprocessing safe.
        """

        logger.debug('initialising %s', self.get_name())

    def on_terminate(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Ends execution of the process after a `terminate` event.

        Args:
            values: Values that are attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """

        self._terminate_signal = True

    def on_tick(self) -> None:
        """The place to do your work.

        Gets called in regulare intervals detemined by
        `_tick_interval`.
        """
        ...

    def on_interrupt(self, signal_num: int, frame: object) -> None:
        # pylint: disable=unused-argument
        """Stop the running process on interrupt.

        Args:
            signal_num: The signal number that was sent to the process.
            frame: The current stack frame.
        """

        self._terminate_signal = True

    def send_to_main(self, name: str, *values: str, **params: str) -> None:
        """Send an event to the main process.

        Args:
            name: The name of the event.
            *values: A list of values.
            **parameters: A dictionary of parameters.
        """
        try:
            self._from_plugin.put_nowait(
                plkevent.Event(name, *values, **params))
        except queue.Full:
            logger.critical('queue from plugins full')

    def send_busy(self) -> None:
        """Signal the main process that the plugin is busy."""
        if not self._busy:
            self.send_to_main('busy')
            self._busy = True

    def send_idle(self) -> None:
        """Signal the main process that the plugin is idle."""
        if self._busy:
            self.send_to_main('idle')
            self._busy = False

    def is_busy(self) -> bool:
        """Returns if the plugin is currently busy.

        Returns:
            Is the plugin currently busy?
        """
        return self._busy

    def register_for(self, event: str) -> None:
        """Register the plugin to be notified if an event is emitted.

        Args:
            event: The name of the event.
        """

        self._registered_events.append(event)

    def get_registered_events(self) -> list[str]:
        """Get the events to notify the plugin for.

        Returns:
            Returns a list of events the plugin is wants to get
            registered for.
        """
        return self._registered_events.copy()

    def run(self) -> None:
        """Gets called when the process for the plugin is started.

        Will call `on_tick` every `_tick_interval` seconds and then
        wait for any event emitted by the main process.

        If an event is recieved the corresponding `on_EVENT` method is
        called.
        """
        logger.debug('%s running', self.get_name())

        signal.signal(signal.SIGINT, lambda signal_num, frame: ...)#self.on_interrupt)
        signal.signal(signal.SIGTERM, lambda signal_num, frame: ...)#self.on_interrupt)

        self.on_before_run()

        while not self._terminate_signal:
            self.on_tick()
            try:
                event: plkevent.Event = self._to_plugin.get(
                    True, self._tick_interval)
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

    def on_before_run(self) -> None:
        """Create things in the new process."""
        ...

    def on_after_run(self) -> None:
        """Give the plugin a chance to tidy up."""
        ...
