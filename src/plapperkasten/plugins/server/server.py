#!/usr/bin/env python3
"""A very basic WebServer that can communicate with the main process.
"""

import errno
import http.server
import multiprocessing
import os
import pathlib
from plapperkastenserver import config as plkserverconfig
import queue
import signal

from plapperkasten import config as plkconfig
from plapperkasten import event as plkevent
from plapperkasten import keymap
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging
from plapperkasten.plugins.server import plkserver

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Server(plugin.Plugin):
    """The main class of the plugin.

    Set up an instance of plapperkastenserver in its own process.

    Attributes:
        _hostname: The hostname to use.
        _path_eventmap: The path to the events.map.
        _path_espeak_greetings: The path to a file containing greetings.
        _path_espeak_text_blocks: The path to a file containing text
            blocks.
        _port: The prot to use.
        _server: The server object.
        _server_process: The process the server runs in.
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

        user_directory: str = config.get_str('core',
                                             'paths',
                                             'user_directory',
                                             default='~')

        eventmap: str = config.get_str('core',
                                       'paths',
                                       'eventmap',
                                        default='events.map')
        self._path_eventmap: str = f'{user_directory}/{eventmap}'

        greetings: str = config.get_str('plugins',
                                        'server',
                                        'filename_espeak_greetings',
                                         default='espeak_greetings')
        self._path_espeak_greetings: str = f'{user_directory}/{greetings}'

        text_blocks: str = config.get_str('plugins',
                                          'server',
                                          'filename_espeak_text_blocks',
                                           default='espeak_text_blocks')
        self._path_espeak_text_blocks: str = f'{user_directory}/{text_blocks}'


        self._hostname: str = config.get_str('plugins',
                                             'server',
                                             'hostname',
                                             default='localhost')

        self._port: int = config.get_int('plugins',
                                         'server',
                                         'port',
                                         default=8080)

        self._server: plkserver.Server
        self._server_process: multiprocessing.Process
        self._queue: multiprocessing.Queue

    def on_before_run(self) -> None:
        """Create a process for the server to run."""
        cfg: plkserverconfig.Config = plkserverconfig.Config(
                path_base=pathlib.Path(__file__).parent.absolute(),
                path_eventmap=self._path_eventmap,
                path_greetings=self._path_espeak_greetings,
                path_text_blocks=self._path_espeak_text_blocks)
        cfg.html_css_default.append('normalize.css')
        #cfg.html_css_default.append('milligram.min.css')
        cfg.html_css_default.append('style.css')

        self._queue = multiprocessing.Queue()

        self._server = plkserver.Server(
                (self._hostname, self._port), plkserver.RequestHandler)
        self._server.init(cfg, self._queue)
        self._server_process = multiprocessing.Process(
                target=self._server.serve_forever)
        self._server_process.start()

    def on_tick(self) -> None:
        """The place to do your work.

        Gets called in regular intervals detemined by
        `_tick_interval`.
        """
        try:
            event: plkevent.Event = self._queue.get(
                True, self._tick_interval)
            logger.debug('sending event "%s" to main', event.name)
            self.send_to_main(event.name, *event.values, **event.params)
        except queue.Empty:
            pass
        except ValueError:
            logger.error('server holds a closed queue')

    def on_timeout(self, signum: int, frame: object) -> None:
        """Raises a TimeoutError."""
        raise TimeoutError

    def on_after_run(self) -> None:
        """Give the plugin a chance to tidy up."""
        logger.debug('shutting down server')
        signal.signal(signal.SIGALRM, self.on_timeout)
        signal.alarm(5)
        try:
            self._server.shutdown()
            signal.alarm(0)
        except TimeoutError:
            self._server_process.kill()
        logger.debug('server stopped')
