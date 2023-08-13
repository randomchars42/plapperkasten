#!/usr/bin/env python3
"""A FIFO interface for Plapperkasten.

Read input from a named FIFO pipe.
"""

import errno
import http.server
import os
import pathlib
import queue
import signal

from plapperkasten import config as plkconfig
from plapperkasten import event as plkevent
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class InputNamedPipe(plugin.Plugin):
    """The main class of the plugin.

    Sets up a FIFO named pipe which will be read non-blockingly in
    intervals of `_read_interval` milliseconds.

    Attributes:
        _user_directory: Path to the user's application directory as used by the
            core (str).
        _pipe_name: The name of the pipe.
        _path: The location of the pipe.
        _read_interval: The interval to check for new input in milliseconds.
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

        self._user_directory: str = config.get_str('core',
                                          'paths',
                                          'user_directory',
                                          default='~')

        self._pipe_name: str = config.get_str('plugins',
                                          'inputnamedpipe',
                                          'name',
                                          default='pipe_in')

        self._path: pathlib.Path

        self._read_interval: int = config.get_int('plugins',
                                          'inputnamedpipe',
                                          'read_interval',
                                          default=200)

    def run(self) -> None:
        """Check status of the gpio pins at regular intervals.

        Needs to reimplement `plugin.Plugin.run()` to use the
        contextmanager implemented by `gpiodmonitor`.
        """

        logger.debug('%s running', self.get_name())

        signal.signal(signal.SIGINT, self.on_interrupt)
        signal.signal(signal.SIGTERM, self.on_interrupt)

        self.on_before_run()

        # only proceed if the pipe has been created
        if self._path:
            logger.debug('opening non blocking FIFO named pipe...')
            try:
                io = os.open(self._path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                logger.error('could not open pipe for reading')
                self._terminate_signal = True

            while not self._terminate_signal:
                # TODO do something here?
                try:
                    buffer = os.read(io, 1024).decode(encoding="utf-8")
                except OSError as error:
                    if error.errno in [errno.EAGAIN, errno.EWOULDBLOCK]:
                        buffer = ""
                    else:
                        logger.error('could not read pipe')
                        self._terminate_signal = True

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
            os.close(io)
            self.on_after_run()

        logger.debug('%s exited main loop', self.get_name())

    def on_before_run(self) -> None:
        """Create the pipe if it does not exist."""

        path: pathlib.Path = pathlib.Path(self._user_directory, self._pipe_name)

        try:
            path.resolve()
        except RuntimeError:
            logger.error('could not resolve path "%s" (infinite recursion)',
                         str(path))

        try:
            os.mkfifo(str(path))
        except OSError as error:
            if error.errno != errno.EEXIST:
                logger.error('could not create pipe at "%s"',
                             str(path))
        if path.exists():
            if path.is_fifo():
                self._path = path
            else:
                logger.error('path "%s" exists but is no FIFO pipe',
                             str(path))


    def on_after_run(self) -> None:
        """Give the plugin a chance to tidy up."""
        ...

class WebinterfaceServer(http.server.BaseHTTPRequestHandler):
    ...
