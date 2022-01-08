#!/usr/bin/env python3

import logging
from  multiprocessing import Process, Queue
from queue import Empty
import signal

from boxhead import boxhead

logger = logging.getLogger(__name__)

class Plugin(Process):
    """Base class for plugins using their own process.

    Modified after: https://pymotw.com/3/multiprocessing/communication.html
    """

    def __init__(self, name: str, main: boxhead.BoxHead,
            to_plugin: Queue, from_plugin: Queue) -> None:
        """Initialises the plugin and then calls `on_init()`.

        All parameters which are passed in by reference may not be stored in
        this object to avoid concurrent access by different entities to the
        same resource.

        There should be no need to overwrite this function as it calls
        `on_init()` which may more easily be overwriten by subclasses.

        Args:
            name: The name of this plugin as its known to the main
                process.
            main: The instance of the central module.
        """

        Process.__init__(self)
        self._name: str = name
        ##signal.signal(signal.SIGTERM, self.handle_signal)
        self._tick_interval: int = 1
        self._terminate_signal: bool = False
        self._to_plugin: Queue = to_plugin
        self._from_plugin: Queue = from_plugin
        self.on_init(main)
        print('initialised {}'.format(self.get_name()))

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

        print('initialising {}'.format(self.get_name()))

    def on_terminate(self) -> None:
        """Ends execution of the process after a `terminate` event."""

        self._terminate_signal = True

    def on_tick(self) -> None:
        """The place to do your work.

        Gets called in regulare intervals detemined by
        `__tick_interval`.
        """
        print('{} working'.format(self.get_name()))

    def on_interrupt(self, signal_num: int, frame: object) -> None:
        """Stop the running process on interrupt.

        Args:
            signal_num: The signal number that was sent to the process.
            frame: The current stack frame.
        """

        self._terminate_signal = True

    def run(self) -> None:
        print('{} running'.format(self.get_name()))

        signal.signal(signal.SIGINT, self.on_interrupt)
        signal.signal(signal.SIGTERM, self.on_interrupt)

        while not self._terminate_signal:
            self.on_tick()
            try:
                event: object = self._to_plugin.get(True, self._tick_interval)
                if hasattr(self, 'on_' + event):
                    getattr(self, 'on_' + event)()
                else:
                    logger.error('no method for event {} defined by {}'.format(
                        event, self.get_name()))
            except Empty:
                pass
            except ValueError:
                logger.error('{} holds a closed queue'.format(
                    self.get_name()))

    def __del__(self) -> None:
        print('{} is stopping'.format(self.get_name()))
