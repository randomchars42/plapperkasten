"""Checks for web shutdown controls and RFID status across the event bus."""

import http.client
from html.parser import HTMLParser
import json
from pathlib import Path
import queue
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import evdev

import plapperkasten
from plapperkasten.config import Config
from plapperkasten.event import Event
from plapperkasten.eventmap import EventMap
from plapperkasten.plapperkasten import Plapperkasten
from plapperkasten.plugins.autoshutdown.autoshutdown import Autoshutdown
from plapperkasten.plugins.inputdevinputevent.inputdevinputevent import Inputdevinputevent
from plapperkasten.plugins.server.server import Server


class AutoshutdownTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = Config(self.directory.name)
        config.set_int('plugins', 'autoshutdown', 'idle_time', value=3)
        self.plugin = Autoshutdown('Autoshutdown', config, Mock(), Mock())
        self.plugin.send_to_main = Mock()

    def test_pause_prevents_shutdown_and_resume_starts_fresh_timeout(self):
        plugin = self.plugin
        plugin.on_idle()
        plugin.on_tick()
        plugin.on_tick()
        plugin.on_autoshutdown_pause()
        for _ in range(10):
            plugin.on_tick()
        self.assertEqual(plugin._countdown, 1)
        self.assertNotIn('shutdown', [c.args[0] for c in plugin.send_to_main.call_args_list])
        plugin.on_autoshutdown_resume()
        plugin.send_to_main.reset_mock()
        plugin.on_tick()
        plugin.on_tick()
        plugin.send_to_main.assert_not_called()
        plugin.on_tick()
        plugin.send_to_main.assert_called_once_with('shutdown')

    def test_busy_and_idle_changes_do_not_clear_pause(self):
        plugin = self.plugin
        plugin.on_autoshutdown_pause()
        plugin.on_busy()
        plugin.on_idle()
        for _ in range(5):
            plugin.on_tick()
        self.assertTrue(plugin._paused)
        self.assertEqual(plugin._countdown, 3)
        plugin.on_busy()
        plugin.on_autoshutdown_resume()
        for _ in range(5):
            plugin.on_tick()
        self.assertEqual(plugin._countdown, 3)
        plugin.on_idle()
        plugin.on_tick()
        self.assertEqual(plugin._countdown, 2)

    def test_duplicate_resume_does_not_extend_running_countdown(self):
        plugin = self.plugin
        plugin.on_idle()
        plugin.on_autoshutdown_pause()
        plugin.on_autoshutdown_pause()
        plugin.on_autoshutdown_resume()
        plugin.on_tick()
        plugin.on_autoshutdown_resume()
        self.assertEqual(plugin._countdown, 2)

    def test_initial_and_changed_status_are_reported_by_plugin(self):
        plugin = self.plugin
        plugin.on_before_run()
        plugin.send_to_main.assert_called_with('autoshutdown_status', paused='false')
        plugin.on_autoshutdown_pause()
        plugin.send_to_main.assert_called_with('autoshutdown_status', paused='true')
        plugin.on_autoshutdown_resume()
        plugin.send_to_main.assert_called_with('autoshutdown_status', paused='false')


class WebStatusTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        Path(self.directory.name, 'events.map').write_text('00017|play\n')
        self.config = Config(self.directory.name)
        self.config.set_str('plugins', 'server', 'hostname', value='127.0.0.1')
        self.config.set_int('plugins', 'server', 'port', value=0)
        self.outgoing = queue.Queue()
        self.server = Server('Server', self.config, queue.Queue(), self.outgoing)
        self.autoshutdown = Autoshutdown('Autoshutdown', self.config,
                                        queue.Queue(), self.outgoing)
        self.core = Plapperkasten()
        self.core._eventmap = EventMap(self.config)
        self.core._terminate_signal = self.core._shutdown_signal = False
        self.core._queues_to_plugins = {}
        for plugin in (self.server, self.autoshutdown):
            name = plugin.get_name().lower()
            self.core._queues_to_plugins[name] = plugin._to_plugin
            for event in plugin.get_registered_events():
                self.core.register(event, name)
        self.server.on_before_run()
        self.addCleanup(self.server.on_after_run)

    def relay_events(self):
        """Run the real routing and plugin handlers without hardware or poweroff."""
        for _ in range(20):
            processed = False
            while not self.outgoing.empty():
                # Simulate an older device config with none of the new events.
                self.core.process_event(self.outgoing.get_nowait(), ['play'])
                processed = True
            for plugin in (self.server, self.autoshutdown):
                while not plugin._to_plugin.empty():
                    event = plugin._to_plugin.get_nowait()
                    getattr(plugin, 'on_' + event.name)(*event.values, **event.params)
                    processed = True
            if not processed:
                return
        self.fail('Event routing did not settle')

    def request(self, method='GET', path='/api/status', body=None):
        connection = http.client.HTTPConnection(
            '127.0.0.1', self.server._server.server_address[1], timeout=2)
        try:
            connection.request(method, path, body,
                               {'Content-Type': 'application/x-www-form-urlencoded'})
            response = connection.getresponse()
            content = response.read().decode('utf-8')
            return response.status, dict(response.getheaders()), content
        finally:
            connection.close()

    def status(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('application/json', headers['Content-Type'])
        return json.loads(body)

    def test_page_revalidates_and_loads_versioned_stylesheets(self):
        status, headers, page = self.request('GET', '/main?tab=spotify')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-cache')

        class Stylesheets(HTMLParser):
            def __init__(self):
                super().__init__()
                self.urls = []

            def handle_starttag(self, tag, attributes):
                attributes = dict(attributes)
                if tag == 'link' and attributes.get('rel') == 'stylesheet':
                    self.urls.append(attributes['href'])

        stylesheets = Stylesheets()
        stylesheets.feed(page)
        self.assertEqual(len(stylesheets.urls), 2)
        for url in stylesheets.urls:
            self.assertIn('?v=', url)
            status, _, css = self.request('GET', '/' + url)
            self.assertEqual(status, 200)
            if url.startswith('style.css?'):
                self.assertIn('#tab_4:checked ~ #content_tab_4', css)

    def read_card(self, card_id):
        """Feed digit key presses and ENTER through the actual reader decoder."""
        config_path = Path(plapperkasten.__file__).parent / 'plugins/inputdevinputevent/config.yaml'
        self.config.load_from_path(config_path)
        plugin = Inputdevinputevent('Inputdevinputevent', self.config,
                                    queue.Queue(), self.outgoing)
        events = [evdev.InputEvent(0, 0, evdev.ecodes.EV_KEY,
                                  getattr(evdev.ecodes, 'KEY_' + digit), 1)
                  for digit in card_id]
        # Release events and repeated empty ENTER presses must not create reads.
        events += [evdev.InputEvent(0, 0, evdev.ecodes.EV_KEY, evdev.ecodes.KEY_ENTER, value)
                   for value in (0, 1, 1)]

        class Reader:
            name = 'test RFID reader'

            def read(self):
                return iter(events)

        reader = Reader()
        plugin._selector = Mock()
        plugin._selector.select.return_value = [(SimpleNamespace(fileobj=reader), 1)]
        plugin._current_input = {reader.name: ''}
        with patch('plapperkasten.plugins.inputdevinputevent.inputdevinputevent.evdev.InputDevice', Reader):
            plugin.on_tick()
        self.relay_events()

    def test_status_is_unknown_until_reported_and_head_has_no_body(self):
        self.assertEqual(self.status(), {
            'last_rfid_card': None, 'autoshutdown_paused': None})
        get_status, get_headers, get_body = self.request()
        status, headers, body = self.request('HEAD')
        self.assertEqual(status, get_status)
        self.assertEqual(headers['Content-Length'], get_headers['Content-Length'])
        self.assertEqual(body, '')
        self.assertGreater(len(get_body), 0)

    def test_web_pause_and_resume_wait_for_confirmed_state(self):
        self.autoshutdown.on_before_run()
        self.relay_events()
        self.assertIs(self.status()['autoshutdown_paused'], False)
        status, _, _ = self.request('POST', '/action', 'autoshutdown_pause=Pause')
        self.assertEqual(status, 200)
        self.assertIs(self.status()['autoshutdown_paused'], False)
        self.relay_events()
        self.assertTrue(self.autoshutdown._paused)
        self.assertIs(self.status()['autoshutdown_paused'], True)
        status, _, page = self.request('GET', '/main')
        self.assertEqual(status, 200)
        self.assertIn('>Paused</span>', page)
        self.assertIn("fetch('/api/status'", page)
        status, _, _ = self.request('POST', '/action', 'autoshutdown_resume=Resume')
        self.assertEqual(status, 200)
        self.relay_events()
        self.assertFalse(self.autoshutdown._paused)
        self.assertIs(self.status()['autoshutdown_paused'], False)

    def test_new_rfid_card_is_displayed_without_mapping_or_service_exit(self):
        self.read_card('0012345678')
        self.assertEqual(self.status()['last_rfid_card'], '0012345678')
        self.assertFalse(self.core._terminate_signal)
        status, _, page = self.request('GET', '/main')
        self.assertEqual(status, 200)
        self.assertIn('>0012345678</code>', page)
        self.read_card('0098765432')
        self.assertEqual(self.status()['last_rfid_card'], '0098765432')

    def test_mapped_card_still_triggers_action_and_web_playlist_is_not_card_read(self):
        player = queue.Queue()
        self.core._queues_to_plugins['player'] = player
        self.core.register('play', 'player')
        self.read_card('00017')
        self.assertEqual(player.get_nowait().name, 'play')
        self.assertEqual(self.status()['last_rfid_card'], '00017')
        self.read_card('00222')
        status, _, _ = self.request('POST', '/playlist', '00017=Album')
        self.assertEqual(status, 200)
        self.relay_events()
        self.assertEqual(player.get_nowait().name, 'play')
        self.assertEqual(self.status()['last_rfid_card'], '00222')

    def test_five_percent_web_presets_route_to_the_shared_volume_control(self):
        observer = queue.Queue()
        self.core._queues_to_plugins['volume_observer'] = observer
        self.core.register('volume', 'volume_observer')
        status, _, page = self.request('GET', '/main')
        self.assertEqual(status, 200)
        for level in (0, 5, 15, 25):
            self.assertIn(f'name="{level}" value="{level} %"', page)
            self.assertEqual(self.request('POST', '/action', urlencode({str(level): f'{level} %'}))[0], 200)
            self.relay_events()
            event = observer.get_nowait()
            self.assertEqual((event.name, event.values), ('volume', [str(level)]))

    def test_playlist_button_escapes_long_titles_and_submits_the_mapping_id(self):
        title = 'Die drei ??? – Ein langes Abenteuer & "Freunde" <Band 1>'
        source = f'Music/{title}.m3u'
        Path(self.directory.name, 'events.map').write_text(
            f'00017|load_source|use=Mpdclient|key={source}\n', encoding='utf-8')
        self.core._eventmap = EventMap(self.config)
        player = queue.Queue()
        self.core._queues_to_plugins['player'] = player
        self.core.register('load_source', 'player')

        class PlaylistButton(HTMLParser):
            attributes = None
            text = ''
            inside = False

            def handle_starttag(self, tag, attributes):
                attributes = dict(attributes)
                if tag == 'button' and attributes.get('name') == '00017':
                    self.attributes = attributes
                    self.inside = True

            def handle_endtag(self, tag):
                if tag == 'button':
                    self.inside = False

            def handle_data(self, data):
                if self.inside:
                    self.text += data

        status, _, page = self.request('GET', '/main?tab=playlists')
        self.assertEqual(status, 200)
        self.assertNotIn('<Band 1>', page)
        button = PlaylistButton()
        button.feed(page)
        self.assertEqual(button.text, title)
        self.assertEqual(button.attributes['type'], 'submit')
        body = urlencode({button.attributes['name']: button.attributes['value']})
        self.assertEqual(self.request('POST', '/playlist', body)[0], 200)
        self.relay_events()
        event = player.get_nowait()
        self.assertEqual(event.params, {'use': 'Mpdclient', 'key': source})

    def test_card_text_is_escaped_and_status_poll_does_not_change_state(self):
        self.server.on_rfid_read('<script>alert(1)</script>')
        _, _, page = self.request('GET', '/main')
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
        for _ in range(3):
            self.status()
        self.assertTrue(self.outgoing.empty())
        snapshot = self.server._server.get_status()
        snapshot['last_rfid_card'] = 'different'
        self.assertEqual(self.status()['last_rfid_card'], '<script>alert(1)</script>')

    def test_manual_shutdown_still_works_while_paused(self):
        self.autoshutdown.on_autoshutdown_pause()
        self.core.process_event(Event('shutdown'), [])
        self.assertTrue(self.core._shutdown_signal)
        self.assertTrue(self.core._terminate_signal)


if __name__ == '__main__':
    unittest.main()
