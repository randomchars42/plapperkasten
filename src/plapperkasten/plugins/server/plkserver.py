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
        ('GET', '/answer/{answer}', 'check_answer'),
        ('GET', '/playlists', 'display_playlists'),
        ('POST', '/playlists', 'load_playlist')
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

    def display_playlists(self,
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

        path: pathlib.Path = pathlib.Path(
                self.config.custom['path_eventmap']).expanduser().resolve()
        lines: list[str] = path.read_text('utf-8').splitlines()

        buttons: str = '<ul>'

        for line in lines:
            value: str = '???'
            name: str = line.split('|', 1)[0]
            match: Optional[Match] = re.search(r'key=(.*\/)([^\/]*).m3u', line)
            if not match:
                continue
            value = match.group(2)
            buttons += f"<li><input type=\"submit\" name=\"{name}\" "\
                    f"value=\"{value}\"/></li>"
        buttons += '</ul>'

        template: SimpleTemplatePage = SimpleTemplatePage(
                    self.config,
                    template='display_playlists.html')
        template.variables['buttonlist'] = buttons
        response.set_body(template.compile())

    def load_playlist(self,
                     request: Request,
                     response: Response,
                     headers_only: bool) -> None:
        """Store the uploaded file.

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
            # -> the request should only hold on item
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        key: str = request.data[0].name

        if not key.isdigit():
            # this should be only digits
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        value: str = request.data[0].value

        if not re.fullmatch(r'[a-zA-Z0-9 \.&-_]+', value):
            # only accept alphanumeric characters, blanks, dashes,
            # underscores, dots
            raise HTTPError('irregular request data',
                            http.HTTPStatus.BAD_REQUEST)

        self.server.send_to_main('raw', key)
        self.display_playlists(request, response, headers_only)
