"""Server for ."""

import http
import pathlib
import re

from typing import Match, Optional

from plapperkastenserver import htmltemplate
from plapperkastenserver.httprequesthandler import HTTPRequestHandler
from plapperkastenserver.request import Request
from plapperkastenserver.response import Response
from plapperkastenserver.exceptions import HTTPError

HOSTNAME = "localhost"
PORT = 8080


class SimpleTemplatePage(htmltemplate.HTMLTemplate):
    """A demo page."""
    def __init__(self, config: plkconfig.Config, template: str) -> None:
        # pylint: disable=too-many-arguments
        """Contructor."""
        super().__init__(config)
        self.set_template_file(template)

class RequestHandler(HTTPRequestHandler):
    """A demo."""
    rules = [
        ('GET', '/answer/{answer}', 'check_answer'),
        ('GET', '/playlists', 'display_playlists'),
        ('POST', '/playlist', 'load_playlist')
    ]

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

        path: str = '/data/eike/Config/plapperkasten/events.map'
        lines: list[str] = pathlib.Path(path).read_text('utf-8').splitlines()

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
                    template='display_resources.html')
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

        template: SimpleTemplatePage = SimpleTemplatePage(
                    self.config,
                    template='result.html')
        template.variables = {
                'text': f"{key} - {value}"}
        response.set_body(template.compile())

