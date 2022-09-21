#!/usr/bin/env python3
"""A plugin controlling a python MPD client.
"""

import time

import mpd

from typing import Any

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging
from mpdclient import statusmap

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Mpdclient(plugin.Plugin):
    """Plugin controlling a python MPD client.

    Attributes:
        _statusmap: The statusmap object to query status from.
        _status: The current status.
        _connected: Indicates if a connection to MPD has been
            established.
        _active: Is this plugin the one which handles the current
            source?
        _mpdclient: The MPD client.
        _host: The host where MPD resides.
        _port: The port to use for connecting.
        _last_check: When was the playlist last checked?
        _last_check_result: The result of the last check.
        _last_save: When was the status last saved to the statusmap?
        _save_min_interval: The minimum interval between two saves in
            seconds.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """This gets called by the constructor.

        Args:
            config: The configuration.
        """

        self._tick_interval: int = config.get_int('plugins',
                                                  'mpdclient',
                                                  'interval_poll',
                                                  default=5)
        self._save_min_interval: int = config.get_int('plugins',
                                                      'mpdclient',
                                                      'save_min_interval',
                                                      default=5)
        self._host: str = config.get_str('plugins',
                                         'mpdclient',
                                         'host',
                                         default='localhost')
        self._port: int = config.get_int('plugins',
                                         'mpdclient',
                                         'port',
                                         default=6600)

        self._connected: bool = False
        self._active: bool = False
        self._statusmap: statusmap.StatusMap = statusmap.StatusMap(config)
        self._status: statusmap.Status = statusmap.Status()
        self._last_save: int = 0
        self._last_check: int = 0
        self._last_check_result: bool = False

        self.register_for('load_source')
        self.register_for('toggle')
        self.register_for('play')
        self.register_for('stop')
        self.register_for('next')
        self.register_for('previous')

    def on_before_run(self) -> None:
        """Instantiate the MPD client.

        Do not do this in `on_init` as then the subprocess is not yet
        running and the object has to be copied into the process and
        havoc ensues in tidying up.
        """

        # deliberately disable type checking for _mpdclient
        # the class is built using mixins and mypy cannot determine its member
        # functions
        self._mpdclient: Any = mpd.MPDClient()
        try:
            self._mpdclient.connect(self._host, self._port)
            self._connected = True
        except ConnectionError:
            logger.error('could not connect to MPD')

    def on_connection_error(self) -> None:
        """Log event and mark as not connected."""
        self._connected = False
        logger.error('lost connection to MPD')

    def on_tick(self) -> None:
        """Called every `_tick_interval` [s] while the process runs.

        Use this function if you have to do anything at regular
        intervals.

        If you only need to respond to events just register for the
        events in `on_init` and make sure you write the corresponding
        `on_EVENT` functions.
        """

        if self._connected:
            try:
                self.check_mpd(save=True)
            except ConnectionError:
                self.on_connection_error()

    def on_after_run(self) -> None:
        """Close the connection and disconnect."""
        super().on_after_run()
        if self._connected:
            try:
                self._mpdclient.stop()
                self._mpdclient.close()
                self._mpdclient.disconnect()
            except ConnectionError:
                self.on_connection_error()

    def on_load_source(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Gets called if a new source is to be loaded.

        Args:
            values: Values attached to the event (ignored).
            params: Parameters attached to the event. Of those only
                `use` and `key` are used.
        """

        if not all(x in params for x in ('use', 'key')):
            logger.error('malformed load_source event')
            return
        elif not params['use'] == self.get_name():
            # event meant for another plugin
            self._active = False
            self.send_idle()
            return

        # create a playlist from the resource and play it
        status: statusmap.Status = self._statusmap.get_status(params['key'])
        if status.key == '':
            # empty status means that there's no entry with params['key'] as
            # key in the statusmap
            status.key = params['key']
        self.apply_status(status)

        try:
            self._mpdclient.play()
        except mpd.CommandError:
            logger.error('could not apply status')
            return
        except ConnectionError:
            self.on_connection_error()
            return

        # mark as active so that `on_play()`, `on_toggle()`, `on_stop()`,
        # `on_next()` and `on_prev()` react when called
        self._active = True
        # since music is playing inhibit auto shutdown etc. by claiming to
        # be busy
        self.send_busy()

        if not self.check_mpd(save=True):
            self._active = False
            self.send_idle()


    def apply_status(self, status: statusmap.Status) -> None:
        """Apply all parameters to MPD.

        Args:
            status: The status, including playlist / folder, position
                and time.
        """

        if status.key == '' or not self._connected:
            # empty status or not connected
            return

        try:
            # clear the "old" playlist or else the new titles would only be
            # appended and comparisons of playlists or loops etc. fail
            self._mpdclient.clear()

            if status.key[-4:] == '.m3u':
                # the key indicates a playlist to be loaded
                self._mpdclient.load(status.key[:-4])
            else:
                # the key represents a path to a folder the files in which are
                # to be coerced into a playlist
                self._mpdclient.add(status.key)

            self._mpdclient.seek(status.position, status.elapsed)
        except mpd.CommandError:
            logger.error('could not apply status')
            return
        except ConnectionError:
            self.on_connection_error()
            return
        self._status = status

    def query_status(self) -> statusmap.Status:
        """Queries the current status from MPD.

        Returns:
            The current status or an empty status if the connection is
            broken.
        """

        status: statusmap.Status = statusmap.Status()

        if not self._connected:
            return status

        try:
            mpd_status: dict[str, str] = self._mpdclient.status()
            if 'error' in mpd_status:
                raise ConnectionError
            status.position = mpd_status['song']
            status.elapsed = mpd_status['elapsed']
            status.state = mpd_status['state']
        except KeyError:
            logger.error('could not get all information from MPD status')
            return status
        except ConnectionError:
            self.on_connection_error()
            return status

        return status

    def is_current_playlist(self, key: str) -> bool:
        """Compares the playlist (or folder) with MPD playlist.

        There is no easy way to determine whether MPD's current
        playlist / queue is the same as has been loaded by
        `on_load_source()` as MPD. One needs to compare MPD's current
        playlist with a hypthetical, expected playlist.

        In theory the queue should only be altered by another call to
        `on_load_source()` but as many clients could connect to MPD we
        make sure by checking if the current playlist matches what we
        expect.

        Args:
            key: The key of the playlist to compare against MPD's
                playlist.

        Returns:
            True if both playlists match.
        """

        if not self._connected or key == '':
            return False

        try:
            mpd_list: list[str] = self._mpdclient.playlist()
            key_list: list[str]

            # unfortunately MPDClient.playlist(), MPDClient.listplaylist() and
            # MPDClient.search() return their information in different formats
            # with no obvious way to alter the representation
            if key[-4:] == '.m3u':
                key_list = [
                    'file: ' + file
                    for file in self._mpdclient.listplaylist(key[:-4])
                ]
            else:
                key_list = [
                    'file: ' + file['file']
                    for file in self._mpdclient.search('base', key)
                ]

        except mpd.CommandError:
            logger.error('could not apply status')
            return False
        except ConnectionError:
            self.on_connection_error()
            return False

        return mpd_list == key_list

    def check_mpd(self, save: bool = False, force: bool = False) -> bool:
        """Check if MPD is in sync and persist status to statusmap.

        In theory, we should know what MPD is doing but as many clients
        can connect to MPD we make sure by checking.

        This function is called on every play / toggle / pause / next /
        prev event. As those might be emitted very rapidly, e.g., the
        user holds the button pressed, we limit the frequency of checks
        to once every 500 ms. This value is arbitrary and hardcoded...

        Args:
            save: Save the current status in the statusmap?
            force: Force checking / saving?

        Returns:
            True if MPD is connected and in the expected playlist.
        """

        logger.debug('start checking mpd')
        logger.debug('last check: ' + str(self._last_check))
        logger.debug('now: ' + str(time.time()))

        if not force and time.time() < self._last_check + 0.5:
            # the last check was less than 500 ms ago
            logger.debug('no need for further checking')
            logger.debug('returning %s', self._last_check_result)
            return self._last_check_result

        self._last_check_result = False

        if not self._active:
            # this function will might be called by a function triggered by a
            # button (`on_next`, ...); this might hapen happen even if mpd is
            # not active in this case another plugin playing something might
            # be active
            logger.debug('not active')
            return False

        if not self._connected:
            # this function will only be called if we think there's a
            # connection
            logger.debug('not connected')
            return False

        if not self.is_current_playlist(self._status.key):
            # someone must have changed the playlist
            logger.debug('not current playlist')
            return False

        # query the current status (position in playlist, elapsed seconds
        # since beginning of the title) as this changes without us noticing
        # it
        status: statusmap.Status = self.query_status()

        if status.state == 'n/a':
            # the query failed at one point
            logger.debug('query failed')
            return False

        # the status returned by `query_status()` misses the key (= playlist
        # name) but we have veryfied that by calling `is_current_playlist()`
        status.key = self._status.key

        self._status = status
        self._last_check_result = True
        self._last_check = int(time.time())

        if save and (force or
                     time.time() > self._last_save + self._save_min_interval):
            # save the status to file so the user may resume in the event of an
            # unexpected interruption, e.g., an empty battery
            logger.debug('saving status')
            self._statusmap.update_status(self._status)

        if self._status.state == 'play':
            self.send_busy()
        else:
            self.send_idle()

        logger.debug('finished checking mpd')
        return self._last_check_result

    def on_play(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Called on event `play` and starts the playlist at 0.

        Args:
            values: Values attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """

        if not self.check_mpd(save=False, force=False):
            return

        try:
            self._mpdclient.play('0')
        except mpd.CommandError:
            logger.error('could not play')
            return
        except ConnectionError:
            self.on_connection_error()
            return

        self.check_mpd(save=True, force=True)

    def on_toggle(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Pauses / resumes playing.

        Args:
            values: Values attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """

        if not self.check_mpd(save=False, force=False):
            return

        try:
            if self._status.state == 'play':
                # this is not very well documented but empirically seems to
                # pause mpd
                self._mpdclient.pause('1')
            else:
                self._mpdclient.pause('0')
        except mpd.CommandError:
            logger.error('could not toggle')
            return
        except ConnectionError:
            self.on_connection_error()
            return

        self.check_mpd(save=True, force=True)

    def on_stop(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Stops mpd and sets the postion to 0.

        Args:
            values: Values attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """

        if not self.check_mpd(save=False, force=False):
            return

        try:
            self._mpdclient.stop()
            self._mpdclient.seek('0', '0')
        except mpd.CommandError:
            logger.error('could not stop')
            return
        except ConnectionError:
            self.on_connection_error()
            return

        self.check_mpd(save=True, force=True)

    def on_next(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Jumps to the next title.

        Args:
            values: Values attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """

        if not self.check_mpd(save=False, force=False):
            return

        try:
            self._mpdclient.next()
        except mpd.CommandError:
            logger.error('could not jump to next title')
            return
        except ConnectionError:
            self.on_connection_error()
            return

        self.check_mpd(save=True, force=True)

    def on_previous(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Jumps to the previous title.

        Args:
            values: Values attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """

        if not self.check_mpd(save=False, force=False):
            return

        try:
            self._mpdclient.previous()
        except mpd.CommandError:
            logger.error('could not jump to previous title')
            return
        except ConnectionError:
            self.on_connection_error()
            return

        self.check_mpd(save=True, force=True)

