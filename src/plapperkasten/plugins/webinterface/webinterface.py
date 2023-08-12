#!/usr/bin/env python3
"""A web interface Plapperkasten.

Create a very simple webserver to allow some remote manipulation.
"""

import queue
import signal

from plapperkasten import config as plkconfig
from plapperkasten import event as plkevent
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Webinterface(plugin.Plugin):
    """The main class of the plugin.

    Sets up a very simple HTTP server.

    Attributes:
        _hostname: The hostname as defined in the config.
        _port: The port to listen on as defined in the config.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """This gets called by the constructor.

        Use this function to retrieve and store values from the
        configuration. Be careful not to store references as those
        might lead to all sorts of problems related to multiprocessing.

        Using any function but `config.get` will make sure you get
        passed a value (including copies of dictionaries / lists).

        Use this function to register for events, e.g.:
        * `register_for('specialevent')` makes sure `on_specialevent`
          gets called everytime `specialevent` is emitted by the main
          process

        You can define after which interval `on_tick` is called by
        setting `_tick_interval` to the respective value in seconds.

        Args:
            config: The configuration.
        """

        self._hostname: str = config.get_str('plugins',
                                          'webinterface',
                                          'hostname',
                                          default='localhost')

        self._port: int = config.get_int('plugins',
                                          'webinterface',
                                          'port',
                                          default=8080)

    def run(self) -> None:
        """Check status of the gpio pins at regular intervals.

        Needs to reimplement `plugin.Plugin.run()` to use the
        contextmanager implemented by `gpiodmonitor`.
        """

        logger.debug('%s running', self.get_name())

        signal.signal(signal.SIGINT, self.on_interrupt)
        signal.signal(signal.SIGTERM, self.on_interrupt)

        self.on_before_run()

        while not self._terminate_signal:
            # TODO do something here?
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
