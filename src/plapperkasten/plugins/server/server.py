#!/usr/bin/env python3
"""A very basic WebServer that can communicate with the main process.
"""

import errno
import http.server
import multiprocessing
import os
import pathlib
from plapperkastenserver import plapperkastenserver
from plapperkastenserver import config as plkconfig
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

        self._user_directory: str = config.get_str('core',
                                                   'paths',
                                                   'user_directory',
                                                   default='~')

        self._delimiter: str = config.get_str('core',
                                              'mapping',
                                              'delimiter',
                                              default='|')

        self._hostname: str = config.get_str('plugins',
                                             'server',
                                             'hostname',
                                             default='localhost')

        self._port: int = config.get_int('plugins',
                                         'server',
                                         'port',
                                         default=8080)

        self._server: plapperkastenserver.PlapperkastenServer

    def on_before_run(self) -> None:
        """Create a process for the server to run."""
        cfg: plkconfig.Config = plkconfig.Config()

        server: plapperkastenserver.PlapperkastenServer = \
                plapperkastenserver.PlapperkastenServer(
                        (self._hostname, self._port),
                         plkserver.RequestHandler)
        server.init(cfg)
        self.server_process: multiprocessing.Process = multiprocessing.Process(
                target=self._server.run_forever)

    def on_tick(self) -> None:
        """The place to do your work.

        Gets called in regular intervals detemined by
        `_tick_interval`.
        """


    def on_after_run(self) -> None:
        """Give the plugin a chance to tidy up."""
        logger.debug('shutting down server')
        self._server.shutdown()
        logger.debug('server stopped')
