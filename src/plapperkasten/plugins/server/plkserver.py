"""Server for ."""

import http
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

from typing import Match, Optional

from plapperkasten import event as plkevent

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
        super().init(config)

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
        ('GET', '/main', 'display_main'),
        ('POST', '/playlist', 'load_playlist'),
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


    def display_main(self,
                     request: Request,
                     response: Response,
                     headers_only: bool) -> None:
        """Display an upload form.

        Args:
            request: The request sent by the client.
            response: The response to build.
            headers_only: Omit the body?
        """
        if headers_only:
            response.set_status(http.HTTPStatus.OK)
            return

        path_eventmap: str = self.config.custom['path_eventmap']
        path_text_blocks: str = self.config.custom['path_text_blocks']
        path_greetings: str = self.config.custom['path_greetings']

        # build a list of mpdclient playlists from in events.map

        path: pathlib.Path = pathlib.Path(path_eventmap).expanduser().resolve()
        lines: list[str] = path.read_text('utf-8').splitlines()

        playlists: str = '<div id="playlists" class="cards">'

        for line in lines:
            value: str = '???'
            name: str = line.split('|', 1)[0]
            match: Optional[Match] = re.search(r'key=(.*\/)([^\/]*).m3u', line)
            if not match:
                continue
            value = match.group(2)
            playlists += f"<input type=\"submit\" name=\"{name}\" "\
                    f"value=\"{value}\" class=\"item\"/>"
        playlists += '</div>'

        # build a list of greetings for espeak

        path = pathlib.Path(path_greetings).expanduser().resolve()
        lines = path.read_text('utf-8').splitlines()

        greetings: str = '<div id="greetings" class="stretch">'
        n: int = 0

        for line in lines:
            greetings += f"<input type=\"radio\" name=\"greeting\" "\
                    f"value=\"{line}\" id=\"greeting_{n}\"/> "\
                    f"<label for=\"greeting_{n}\" class=\"item\">{line}</label>"
            n += 1
        greetings += '</div>'

        # build a list of text blocks for espeak

        path = pathlib.Path(path_text_blocks).expanduser().resolve()
        lines = path.read_text('utf-8').splitlines()

        text_blocks: str = '<div id="text_blocks" class="stretch">'
        n = 0

        for line in lines:
            text_blocks += f"<input type=\"submit\" "\
                    f"name=\"text_block_{n}\" value=\"{line}\" class=\"item\"/>"
        text_blocks += f"<input type=\"text\" name=\"text_block_text\" "\
                "class=\"item\"/>"\
                f"<input type=\"submit\" name=\"text_block_use\" "\
                f"value=\"submit\" class=\"item\"/>"
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
        for action in [('volume_increase', '-'), ('volume_decrease', '+')]:
            controls_volume += f"<input type=\"submit\" class=\"item\" "\
                    f"name=\"{action[0]}\" value=\"{action[1]}\"/></li>"
        controls_volume += '</div>'

        controls_volume_max: str = '<div id="sound_max" class="row_stretch">'
        for action in [('10', '10 %'), ('20', '20 %'), ('30', '30 %'),
                       ('40', '40 %'), ('50', '50 %'), ('60', '60 %'),
                       ('70', '70 %'), ('80', '80 %'), ('90', '90 %'),
                       ('100', '100 %')]:
            controls_volume_max += f"<input type=\"submit\" class=\"item\" "\
                    f"name=\"{action[0]}\" value=\"{action[1]}\"/></li>"
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
        response.set_body(template.compile())

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
                print(item.name)
                # TODO
                #self.server.send_to_main(item.name)
                self.display_main(request, response, headers_only)
            if not re.fullmatch(r'[a-zA-Z0-9ÄÜÖäüöß \.&-_,\?]+', item.value):
                # only accept alphanumeric characters, blanks, dashes,
                # underscores, dots, question marks and commas
                raise HTTPError('irregular request data',
                                http.HTTPStatus.BAD_REQUEST)
            if item.name.startswith('greeting'):
                sentence = f"{item.value} {sentence}"
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

        if not 0 < len(request.data) < 4:
            # the request may hold a greeting, may hold a text block
            # and the data from the submit button
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        for item in request.data:
            if item.value == '':
                continue
            if item.name in ['10', '20', '30', '40', '50', '60', '70',
                             '80', '90', '100']:
                self.server.send_to_main('volume_max', item.name)
            else:
                self.server.send_to_main(item.name)

        self.display_main(request, response, headers_only)
