#!/usr/bin/env python3
"""A FIFO interface for Plapperkasten.

Read input from a named FIFO pipe:
Input is read in chunks of at most 1024 bytes per tick.
(see also: _tick_interval; configurable via read_interval [ms]).
Input needs to be in "utf-8", delimited by "\n".

A request should be structured like a keymap entry (see keymap.py):

KEY|DATUM1|DATUM2|KEYWORD3=DATUM3|KEYWORD4=DATUM4|...

This will then be translated into an event with KEY as event name and
the rest as values or parameters, respectively.

If you want to send a raw event your input to the pipe would need to
look like this:

raw|0123456789\n

This would make the main application lookup "0123456789" in the
events.map annd if found send the corresponding event.

Or you could send an event like this:

load_source|use=Mpdclient|key=/path/to/my/playlist.m3u\n

or

control_play\n

The default delimiter is "|" but can be changed in the config
(core.mapping.delimiter; be careful! this changes a lot of things!).

"""

import errno
import http.server
import os
import pathlib
import queue
import signal

from plapperkasten import config as plkconfig
from plapperkasten import event as plkevent
from plapperkasten import keymap
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class InputNamedPipe(plugin.Plugin):
    """The main class of the plugin.

    Sets up a FIFO named pipe which will be read non-blockingly in
    intervals of `_read_interval` milliseconds.

    Attributes:
        _buffer: A buffer for the chunks read from the pipe.
        _delimiter: The delimiter used in KeyMaps.
        _io: The handle to the pipe.
        _path: The location of the pipe.
        _pipe_name: The name of the pipe.
        _user_directory: Path to the user's application directory as used by the
            core (str).
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

        self._pipe_name: str = config.get_str('plugins',
                                          'inputnamedpipe',
                                          'name',
                                          default='plapperkasten_pipe_in')

        self._buffer: str = ''
        self._path: pathlib.Path

        self._tick_interval: float = config.get_int('plugins',
                                          'inputnamedpipe',
                                          'read_interval',
                                          default=200) / 1000

    def on_before_run(self) -> None:
        """Create the pipe if it does not exist and open it for reading."""

        path: pathlib.Path = pathlib.Path(self._user_directory, self._pipe_name)
        # we won't let the main loop start until all is set up
        self._terminate_signal = True

        try:
            path.resolve()
        except RuntimeError:
            logger.error('could not resolve path "%s" (infinite recursion)',
                         str(path))
            return

        try:
            os.mkfifo(str(path))
        except OSError as error:
            if error.errno != errno.EEXIST:
                logger.error('could not create pipe at "%s"',
                             str(path))
                return

        if path.is_fifo():
            self._path = path
            logger.debug('opening non blocking FIFO named pipe...')
            try:
                # open a non-blocking pipe for reading
                self._io = os.open(self._path, os.O_RDONLY | os.O_NONBLOCK)
                # we are ready
                self._terminate_signal = False
            except OSError:
                logger.error('could not open pipe for reading')
                return
        else:
            logger.error('path "%s" exists but is no FIFO pipe',
                         str(path))
            return


    def on_tick(self) -> None:
        """The place to do your work.

        Gets called in regular intervals detemined by
        `_tick_interval`.
        """

        # holds a chunk of decoded input from the pipe
        chunk: str = ''
        # a request as recieved from the pipe
        # a request is a string delimited by "\n" which will be parsed
        request: str = ''

        while not self._terminate_signal:
            try:
                # read at most 1024 bytes and decode to utf-8
                chunk = os.read(self._io, 1024).decode(encoding="utf-8")
            except OSError as error:
                if error.errno in [errno.EAGAIN, errno.EWOULDBLOCK]:
                    # pipe is empty
                    chunk = ""
                else:
                    logger.error('could not read pipe')
                    self._terminate_signal = True

            if not chunk == "":
                # if something was recieved
                # append it to the buffer
                self._buffer += chunk
                # and scan if there are one or more requests separated by
                # "\n"
                while "\n" in self._buffer:
                    # splice a request (everything until the first "\n")
                    # from the front section of the buffer and leave the
                    # rest unchanged on the heap
                    request, self._buffer = self._buffer.split("\n", 1)
                    self.process_request(request)

    def process_request(self, request: str) -> None:
        """Process a request.

        See info at the top for the form a request can take.
        """
        eventname: str
        item: keymap.KeyMapItem
        try:
            eventname, item = keymap.KeyMapLib.process_data(request,
                                                            self._delimiter)
        except ValueError:
            logger.error('recieved malformatted request: "%s"', request)
            # drop malformed request
            return

        self.send_to_main(eventname, *item.values, **item.params)

    def on_after_run(self) -> None:
        """Give the plugin a chance to tidy up."""
        try:
            os.close(self._io)
        except OSError:
            # pipe has probably never been opened
            logger.error('could not close pipe')
