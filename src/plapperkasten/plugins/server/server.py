#!/usr/bin/env python3
"""A very basic WebServer that can communicate with the main process.
"""

import errno
import http.server
import json
import os
import pathlib
from plapperkastenserver import config as plkserverconfig
import socket
import threading
import time

from plapperkasten import config as plkconfig
from plapperkasten import keymap
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging
from plapperkasten.plugins.server import plkserver
from plapperkasten.spotify_sources import favorites_path

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
        _server_thread: The thread the server runs in.
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
        self._spotify_enabled = config.get_bool(
            'plugins', 'spotify', 'enabled', default=False)
        self._path_spotify_favorites = favorites_path(config)

        self._server: plkserver.Server
        self._server_thread: threading.Thread
        self.register_for('rfid_read')
        self.register_for('autoshutdown_status')
        self.register_for('spotify_status')
        self.register_for('spotify_queue')

    def on_spotify_queue(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Cache queue snapshots for the HTTP thread without blocking requests."""
        if not self._spotify_enabled:
            return
        try:
            data = json.loads(params.get('data', ''))
            if not isinstance(data, dict):
                return
            self._server.update_spotify_queue(data)
        except (ValueError, TypeError):
            logger.warning('received an invalid spotify queue snapshot')

    def on_spotify_status(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Expose playback state confirmed by the Spotify plugin."""
        if self._spotify_enabled:
            self._server.update_status(
                spotify_state=params.get('state', 'Unavailable'),
                spotify_track=params.get('track', ''),
                spotify_error=params.get('error', ''))

    def on_rfid_read(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Retain complete card reads, including cards without a mapping."""
        if values and values[0]:
            self._server.update_status(last_rfid_card=values[0])

    def on_autoshutdown_status(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Expose only the state confirmed by the autoshutdown plugin."""
        paused = params.get('paused')
        if paused in ('true', 'false'):
            self._server.update_status(autoshutdown_paused=paused == 'true')

    def on_before_run(self) -> None:
        """Serve in a thread so shutdown can signal the server instance."""
        cfg: plkserverconfig.Config = plkserverconfig.Config(
                path_base=pathlib.Path(__file__).parent.absolute(),
                path_eventmap=self._path_eventmap,
                path_greetings=self._path_espeak_greetings,
                path_text_blocks=self._path_espeak_text_blocks,
                spotify_enabled='true' if self._spotify_enabled else 'false',
                path_spotify_favorites=str(self._path_spotify_favorites))
        cfg.html_css_default.append('normalize.css')
        #cfg.html_css_default.append('milligram.min.css')
        cfg.html_css_default.append('style.css')

        retry_until = time.monotonic() + 60
        while not self._terminate_signal:
            try:
                self._server = plkserver.Server(
                        (self._hostname, self._port), plkserver.RequestHandler)
                break
            except OSError as error:
                if (error.errno in (errno.EADDRNOTAVAIL, socket.EAI_AGAIN,
                                   socket.EAI_NONAME) and
                        time.monotonic() < retry_until):
                    logger.warning('waiting for web bind address %s:%s: %s',
                                   self._hostname, self._port, error)
                    time.sleep(1)
                    continue
                raise RuntimeError(
                    f'Could not start web server on {self._hostname}:{self._port}: '
                    f'{error}. The bind address must belong to this device; '
                    'use 0.0.0.0 for LAN access or 127.0.0.1 for local access.') from error
        else:
            return
        self._server.init(cfg, self._from_plugin)
        self._server_thread = threading.Thread(
                target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        logger.info('web server listening on %s:%s',
                    *self._server.server_address)

    def on_after_run(self) -> None:
        """Give the plugin a chance to tidy up."""
        logger.debug('shutting down server')
        if hasattr(self, '_server_thread') and self._server_thread.is_alive():
            self._server.shutdown()
            self._server_thread.join(timeout=5)
        if hasattr(self, '_server'):
            self._server.server_close()
        logger.debug('server stopped')
