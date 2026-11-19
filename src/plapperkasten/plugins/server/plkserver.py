"""Server for ."""

import http
import html
import json
import multiprocessing
import pathlib
from plapperkastenserver import plapperkastenserver
from plapperkastenserver import htmltemplate
from plapperkastenserver import config as plkserverconfig
from plapperkastenserver.httprequesthandler import HTTPRequestHandler
from plapperkastenserver.request import Request
from plapperkastenserver.response import Response
from plapperkastenserver.exceptions import HTTPError
import queue
import re
import threading

from typing import Match, Optional

from plapperkasten import event as plkevent
from plapperkasten.spotify_sources import Favorites, playlist_uri

class SimpleTemplatePage(htmltemplate.HTMLTemplate):
    """A demo page."""
    def __init__(self, config: plkserverconfig.Config, template: str) -> None:
        # pylint: disable=too-many-arguments
        """Contructor."""
        super().__init__(config)
        self.set_template_file(template)

class Server(plapperkastenserver.PlapperkastenServer):

    def init(self, config: plkserverconfig.Config,
             queue: Optional[multiprocessing.Queue] = None) -> None:
        self.queue: Optional[multiprocessing.Queue] = queue
        self._status_lock = threading.Lock()
        self._status: dict[str, str | bool | None] = {
            'last_rfid_card': None,
            'autoshutdown_paused': None,
        }
        self.spotify_enabled = config.custom.get('spotify_enabled') == 'true'
        self.spotify_favorites = Favorites(pathlib.Path(
            config.custom.get('path_spotify_favorites', 'spotify_favorites.yaml')))
        if self.spotify_enabled:
            self._status.update(spotify_state='Connecting', spotify_track='',
                                spotify_error='')
        super().init(config)

    def update_status(self, **status: str | bool | None) -> None:
        """Share plugin updates with the HTTP thread as one snapshot."""
        with self._status_lock:
            self._status.update(status)

    def get_status(self) -> dict[str, str | bool | None]:
        """Read a consistent copy without exposing the shared dictionary."""
        with self._status_lock:
            return self._status.copy()

    def send_to_main(self, name: str, *values: str, **params: str) -> None:
        """Send an event to the main process.

        Args:
            name: The name of the event.
            *values: A list of values.
            **parameters: A dictionary of parameters.
        """
        try:
            if self.queue:
                self.queue.put_nowait(
                    plkevent.Event(name, *values, **params))
        except queue.Full:
            pass

class RequestHandler(HTTPRequestHandler):
    """A demo."""
    rules = [
        ('GET', '/api/status', 'display_status'),
        ('HEAD', '/api/status', 'display_status'),
        ('GET', '/{name}', 'display_main'),
        ('GET', '/{name}/', 'display_main'),
        ('POST', '/playlist', 'load_playlist'),
        ('POST', '/spotify', 'spotify_playlist'),
        ('POST', '/action', 'load_action'),
        ('POST', '/speak', 'load_text')
    ]

    def __init__(self, request, client_address, server: Server) -> None:
        # pylint: disable=super-init-not-called
        """Initialise.

        Args:
            server_config: A basic
        """
        super().__init__(request=request, client_address=client_address,
                         server=server)
        self.server: Server

    @staticmethod
    def read_optional_lines(filename: str) -> list[str]:
        """Missing playlist and speech files leave their controls empty."""
        try:
            return pathlib.Path(filename).expanduser().read_text('utf-8').splitlines()
        except FileNotFoundError:
            return []

    def display_main(self,
                     request: Request,
                     response: Response,
                     headers_only: bool,
                     name: str = '') -> None:
        """Display an upload form.

        Args:
            request: The request sent by the client.
            response: The response to build.
            headers_only: Omit the body?
        """
        if headers_only:
            response.set_status(http.HTTPStatus.OK)
            return

        # ignore `name`
        name = ''

        path_eventmap: str = self.config.custom['path_eventmap']
        path_text_blocks: str = self.config.custom['path_text_blocks']
        path_greetings: str = self.config.custom['path_greetings']

        # build a list of mpdclient playlists from in events.map

        lines = self.read_optional_lines(path_eventmap)

        playlists: str = '<div id="playlists" class="cards">'

        for line in lines:
            value: str = '???'
            name = line.split('|', 1)[0]
            match: Optional[Match] = re.search(r'key=(.*\/)([^\/]*).m3u', line)
            if not match:
                continue
            value = match.group(2)
            playlists += f"<input type=\"submit\" name=\"{name}\" "\
                    f"value=\"{value}\" class=\"item\"/>"
        playlists += '</div>'

        # build a list of greetings for espeak

        lines = self.read_optional_lines(path_greetings)

        greetings: str = '<div id="greetings" class="stretch">'
        n: int = 0

        for line in lines:
            greetings += f"<input type=\"radio\" name=\"greeting\" "\
                    f"value=\"{line}\" id=\"greeting_{n}\"/> "\
                    f"<label for=\"greeting_{n}\" class=\"item\">{line}</label>"
            n += 1
        greetings += f"<input type=\"radio\" name=\"greeting\" "\
                f"value=\"\" id=\"greeting_{n}\" checked/> "\
                f"<label for=\"greeting_{n}\" class=\"item\">[ - ]</label>"
        greetings += '</div>'

        # build a list of text blocks for espeak

        lines = self.read_optional_lines(path_text_blocks)

        text_blocks: str = '<div id="text_blocks" class="stretch">'
        n = 0

        for line in lines:
            text_blocks += f"<input type=\"submit\" "\
                    f"name=\"text_block_{n}\" value=\"{line}\" class=\"item\"/>"
        text_blocks += f"<input type=\"text\" name=\"text_block_text\" "\
                "class=\"item\"/>"\
                f"<input type=\"submit\" name=\"text_block_use\" "\
                f"value=\"Submit\" class=\"item\"/>"
        text_blocks += '</div>'

        time: str = '<div id="time" class="row_stretch">'
        for action in [('say_date', 'Date'), ('say_time', 'Time'),
                       ('say_day', 'Day')]:
            time += f"<input type=\"submit\" class=\"item\" "\
                    f"name=\"{action[0]}\" value=\"{action[1]}\"/></li>"
        time += '</div>'

        # build a list of actions

        controls_player: str = '<div id="player_controls" class="row_stretch">'
        for action in [('previous', 'Previous'), ('play', 'Play'),
                       ('pause', 'Pause'), ('stop', 'Stop'), ('next', 'Next')]:
            controls_player += f"<input type=\"submit\" "\
                    f"class=\"item {action[0]}\" "\
                    f"name=\"{action[0]}\" value=\"{action[1]}\"/></li>"
        controls_player += '</div>'

        controls_volume: str= '<div id="sound_controls" class="row_stretch">'
        for action in [('volume_decrease', '-'), ('volume_increase', '+')]:
            controls_volume += f"<input type=\"submit\" class=\"item\" "\
                    f"name=\"{action[0]}\" value=\"{action[1]}\"/></li>"
        controls_volume += '</div>'
        controls_volume += '<div id="sound_controls_2" class="row_stretch">'
        for action in [('10', '10 %'), ('20', '20 %'), ('30', '30 %'),
                       ('40', '40 %'), ('50', '50 %'), ('60', '60 %'),
                       ('70', '70 %'), ('80', '80 %'), ('90', '90 %'),
                       ('100', '100 %')]:
            controls_volume += f"<input type=\"submit\" class=\"item\" "\
                    f"name=\"{action[0]}\" value=\"{action[1]}\"/></li>"
        controls_volume += '</div>'

        controls_volume_max: str = '<div id="sound_max" class="row_stretch">'
        for action in [('10', '10 %'), ('20', '20 %'), ('30', '30 %'),
                       ('40', '40 %'), ('50', '50 %'), ('60', '60 %'),
                       ('70', '70 %'), ('80', '80 %'), ('90', '90 %'),
                       ('100', '100 %')]:
            controls_volume_max += f"<input type=\"submit\" class=\"item\" "\
                    f"name=\"max_{action[0]}\" value=\"{action[1]}\"/></li>"
        controls_volume_max += '</div>'

        controls_sounds: str = '<div id="sounds" class="row_stretch">'
        for action in [('error', 'Jump'), ('feedback', 'Beep 1'),
                       ('beep', 'Beep 2')]:
            controls_sounds += f"<input type=\"submit\" class=\"item\" "\
                    f"name=\"{action[0]}\" value=\"{action[1]}\"/></li>"
        controls_sounds += '</div>'

        controls_output: str = '<div id="sound_output" class="row_stretch">'
        for action in [('toggle_pwwp_sink', 'Toggle speaker')]:
            controls_output += f"<input type=\"submit\" class=\"item\" "\
                    f"name=\"{action[0]}\" value=\"{action[1]}\"/></li>"
        controls_output += '</div>'

        template: SimpleTemplatePage = SimpleTemplatePage(
                    self.config,
                    template='display_main.html')
        template.variables['playlists'] = playlists
        template.variables['controls_player'] = controls_player
        template.variables['controls_volume'] = controls_volume
        template.variables['controls_volume_max'] = controls_volume_max
        template.variables['controls_sounds'] = controls_sounds
        template.variables['controls_output'] = controls_output
        template.variables['greetings'] = greetings
        template.variables['text_blocks'] = text_blocks
        template.variables['time'] = time
        status = self.server.get_status()
        paused = status['autoshutdown_paused']
        template.variables['last_rfid_card'] = html.escape(
            str(status['last_rfid_card'] or 'No card read yet'))
        template.variables['autoshutdown_status'] = (
            'Paused' if paused is True else
            'Active' if paused is False else 'Unavailable')
        template.variables['pause_disabled'] = '' if paused is False else 'disabled'
        template.variables['resume_disabled'] = '' if paused is True else 'disabled'
        self.spotify_variables(template, request, status)
        response.set_body(template.compile())

    def spotify_variables(self, template: SimpleTemplatePage, request: Request,
                          status: dict[str, str | bool | None]) -> None:
        """Render favorites as forms that also work without JavaScript."""
        favorite_forms = ''
        favorites_error = ''
        disabled = '' if self.server.spotify_enabled else 'disabled'
        try:
            favorites = self.server.spotify_favorites.load()
            for name in favorites:
                escaped = html.escape(name, quote=True)
                favorite_forms += (
                    '<form method="post" action="/spotify" class="spotify_favorite">'
                    f'<input type="hidden" name="favorite" value="{escaped}"/>'
                    f'<button type="submit" name="action" value="play" '
                    f'class="item" {disabled}>Play {escaped}</button>'
                    f'<button type="submit" name="action" value="remove" '
                    f'aria-label="Remove {escaped}" {disabled}>Remove</button></form>')
            if not favorites:
                favorite_forms = '<p>No saved Spotify playlists yet.</p>'
        except (OSError, ValueError, UnicodeError):
            favorites_error = 'Saved Spotify playlists could not be read.'
        template.variables['spotify_favorites'] = favorite_forms
        template.variables['spotify_favorites_error'] = favorites_error
        template.variables['spotify_disabled'] = disabled
        template.variables['spotify_state'] = html.escape(str(
            status.get('spotify_state') or 'Disabled'))
        template.variables['spotify_track'] = html.escape(str(
            status.get('spotify_track') or ''))
        template.variables['spotify_error'] = html.escape(str(
            status.get('spotify_error') or ''))
        query = {field.name: field.value for field in request.query}
        messages = {
            'saved': 'Playlist saved.',
            'removed': 'Playlist removed.',
            'requested': 'Playback requested. Check the Spotify status below.',
        }
        template.variables['spotify_message'] = messages.get(str(query.get('spotify', '')), '')
        playlist_tab = query.get('tab') == 'playlists'
        template.variables['actions_checked'] = '' if playlist_tab else 'checked'
        template.variables['playlists_checked'] = 'checked' if playlist_tab else ''

    def spotify_playlist(self, request: Request, response: Response,
                         headers_only: bool) -> None:
        # pylint: disable=unused-argument
        """Save, play or remove one playlist; accept only known form fields."""
        if not self.server.spotify_enabled:
            raise HTTPError('Spotify playback is not enabled.',
                            http.HTTPStatus.SERVICE_UNAVAILABLE)
        fields: dict[str, str] = {}
        for field in request.data:
            if (field.name in fields or
                    field.name not in ('action', 'playlist', 'name', 'favorite') or
                    not isinstance(field.value, str)):
                raise HTTPError('Invalid Spotify request.', http.HTTPStatus.BAD_REQUEST)
            fields[field.name] = field.value
        action = fields.get('action')
        favorites = self.server.spotify_favorites
        try:
            if 'favorite' in fields:
                if set(fields) != {'favorite', 'action'}:
                    raise ValueError('Invalid saved playlist request.')
                name = fields['favorite']
                if action == 'remove':
                    favorites.remove(name)
                    result = 'removed'
                elif action == 'play':
                    saved = favorites.load()
                    if name not in saved:
                        raise ValueError('This saved playlist no longer exists.')
                    self.server.send_to_main('load_source', use='Spotify', key=saved[name])
                    result = 'requested'
                else:
                    raise ValueError('Unknown Spotify action.')
            else:
                uri = playlist_uri(fields.get('playlist', ''))
                if action == 'save':
                    favorites.save(fields.get('name', ''), uri)
                    result = 'saved'
                elif action == 'play':
                    self.server.send_to_main('load_source', use='Spotify', key=uri)
                    result = 'requested'
                else:
                    raise ValueError('Unknown Spotify action.')
        except (ValueError, UnicodeError) as error:
            raise HTTPError(str(error), http.HTTPStatus.BAD_REQUEST) from error
        except OSError as error:
            raise HTTPError('Saved Spotify playlists could not be updated.',
                            http.HTTPStatus.SERVICE_UNAVAILABLE) from error
        response.set_status(http.HTTPStatus.SEE_OTHER)
        response.add_header('Location', f'/main?tab=playlists&spotify={result}#spotify')
        response.set_body('')

    def display_status(self,
                       request: Request,
                       response: Response,
                       headers_only: bool) -> None:
        # pylint: disable=unused-argument
        """Return live device state without caching an earlier card read."""
        response.add_header('Cache-Control', 'no-store')
        content = json.dumps(self.server.get_status())
        response.set_body('' if headers_only else content,
                          content_type='application/json')
        if headers_only:
            # Retain the GET headers, including the JSON content length.
            response.add_header('Content-Length', str(len(content.encode('utf-8'))))

    def load_playlist(self,
                     request: Request,
                     response: Response,
                     headers_only: bool) -> None:
        """Try to make `mpd_client` load the sent playlist.

        Args:
            request: The request sent by the client.
            response: The response to build.
            headers_only: Omit the body?
        """
        if headers_only:
            response.set_status(http.HTTPStatus.OK)
            return

        if len(request.data) != 1:
            # the form consists of only submit buttons, only on button
            # can be clicked before the form is submitted
            # -> the request should only hold one item
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        key: str = request.data[0].name

        if not key.isdigit():
            # this should be only digits
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        value: str = request.data[0].value

        if not re.fullmatch(r'[a-zA-Z0-9 \.&-_,]+', value):
            # only accept alphanumeric characters, blanks, dashes,
            # underscores, dots and commas
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        self.server.send_to_main('raw', key)
        self.display_main(request, response, headers_only)

    def load_text(self,
                  request: Request,
                  response: Response,
                  headers_only: bool) -> None:
        """Assemble a text from the sent input for `espeak-ng`.

        Args:
            request: The request sent by the client.
            response: The response to build.
            headers_only: Omit the body?
        """
        if headers_only:
            response.set_status(http.HTTPStatus.OK)
            return

        if not 0 < len(request.data) < 4:
            # the request may hold a greeting, may hold a text block
            # and the data from the submit button
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        sentence: str = ''

        for item in request.data:
            if item.value == '':
                continue
            if item.name in ['say_day', 'say_date', 'say_time']:
               self.server.send_to_main(item.name)
               self.display_main(request, response, headers_only)
            if not re.fullmatch(r'[a-zA-Z0-9ÄÜÖäüöß \.&-_,\?]+', item.value):
                # only accept alphanumeric characters, blanks, dashes,
                # underscores, dots, question marks and commas
                raise HTTPError('irregular request data',
                                http.HTTPStatus.BAD_REQUEST)
            if item.name.startswith('greeting'):
                sentence = f"{item.value} {sentence}"
            elif item.name == 'text_block_use':
                continue
            elif item.name.startswith('text_block'):
                sentence += item.value

        self.server.send_to_main('say', text=sentence)
        self.display_main(request, response, headers_only)

    def load_action(self,
                    request: Request,
                    response: Response,
                    headers_only: bool) -> None:
        """Assemble a text from the sent input for `espeak-ng`.

        Args:
            request: The request sent by the client.
            response: The response to build.
            headers_only: Omit the body?
        """
        if headers_only:
            response.set_status(http.HTTPStatus.OK)
            return

        if len(request.data) != 1:
            # Only the clicked submit button belongs in an action request.
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        for item in request.data:
            if item.value == '':
                continue
            if item.name in ['10', '20', '30', '40', '50', '60', '70',
                             '80', '90', '100']:
                self.server.send_to_main('volume', item.name)
            elif item.name in ['max_10', 'max_20', 'max_30', 'max_40', 'max_50',
                               'max_60', 'max_70', 'max_80', 'max_90',
                               'max_100']:
                self.server.send_to_main('volume_max', item.name.split('_')[1])
            elif item.name in ('previous', 'play', 'pause', 'stop', 'next',
                               'volume_decrease', 'volume_increase', 'error',
                               'feedback', 'beep', 'toggle_pwwp_sink',
                               'autoshutdown_pause', 'autoshutdown_resume'):
                self.server.send_to_main(item.name)
            else:
                raise HTTPError('unknown action', http.HTTPStatus.BAD_REQUEST)

        self.display_main(request, response, headers_only)
