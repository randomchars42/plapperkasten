"""Spotify playlist persistence, web/event routing and local Soloist control."""

import http.client
import json
import logging
from pathlib import Path
import queue
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from plapperkasten.config import Config
from plapperkasten.event import Event
from plapperkasten.plapperkasten import Plapperkasten
from plapperkasten.plugins.server.server import Server
from plapperkasten.plugins.spotify.spotify import Spotify
from plapperkasten.spotify_sources import Favorites, playlist_uri

# Unit tests have no logging consumer process.
logging.getLogger().handlers.clear()


PLAYLIST_ID = '37i9dQZF1DXcBWIGoYBM5M'
URI = f'spotify:playlist:{PLAYLIST_ID}'
LINK = f'https://open.spotify.com/playlist/{PLAYLIST_ID}?si=example'
TRACK_URI = 'spotify:track:' + 'A' * 22
NEXT_URI = 'spotify:track:' + 'B' * 22


class FakeSoloist:
    """Simulate the documented CLI protocol while keeping real event routing."""

    def __init__(self):
        def item(name, uri):
            return {'uri': uri, 'entity_type': 'track', 'decorations': {
                'identity': {'name': name},
                'creators': [{'entity': {'decorations': {'identity': {'name': 'An artist'}}}}],
            }}
        self.snapshot = {
            'type': 'playback_state', 'status': 'idle', 'is_active': False,
            'item': item('A song', TRACK_URI),
            'context': {'uri': URI, 'decorations': {'identity': {'name': 'Bedtime songs'}}},
        }
        self.queue = {'type': 'queue_changed', 'previous': [], 'upcoming': [
            {'uid': 'next', 'source': 'context', 'item': item('Next song', NEXT_URI)},
        ]}
        self.commands = []
        self.failure = None

    def __call__(self, arguments, **options):
        if self.failure:
            raise self.failure
        assert arguments[:2] == ['soloist', 'ctl']
        assert arguments[-2:] == ['--ws', '127.0.0.1:9090']
        assert options['timeout'] > 0
        assert options['check'] is True
        command = arguments[2:-2]
        self.commands.append(command)
        if command[0] == 'activate':
            self.snapshot['is_active'] = True
        elif command[0] == 'play':
            self.snapshot['status'] = 'playing'
        elif command[0] == 'pause':
            self.snapshot['status'] = 'paused'
        output = (json.dumps(self.snapshot) if command[0] == 'now' else
                  json.dumps(self.queue) if command[0] == 'queue' else '')
        return subprocess.CompletedProcess(arguments, 0, output, '')


class FavoritesTests(unittest.TestCase):
    def test_share_links_and_uris_normalize_without_network_requests(self):
        for value in (URI, LINK, f'https://open.spotify.com/intl-de/playlist/{PLAYLIST_ID}/',
                      f'  {URI}  '):
            with self.subTest(value=value):
                self.assertEqual(playlist_uri(value), URI)

    def test_other_hosts_items_and_command_text_are_rejected(self):
        for value in ('', f'https://example.com/playlist/{PLAYLIST_ID}',
                      f'https://open.spotify.com.evil/playlist/{PLAYLIST_ID}',
                      f'https://user@open.spotify.com/playlist/{PLAYLIST_ID}',
                      f'http://open.spotify.com/playlist/{PLAYLIST_ID}',
                      f'https://open.spotify.com/track/{PLAYLIST_ID}',
                      f'https://open.spotify.com/playlist/{PLAYLIST_ID}/extra',
                      f'spotify:track:{PLAYLIST_ID}', URI + '; shutdown',
                      f'https://open.spoti\nfy.com/playlist/{PLAYLIST_ID}',
                      'https://spotify.link/short-link', 'spotify:playlist:123'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                playlist_uri(value)

    def test_favorites_survive_reload_update_and_removal(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'subdirectory/favorites.yaml'
            favorites = Favorites(path)
            favorites.save('Schöne Lieder & Geschichten', LINK)
            self.assertEqual(Favorites(path).load(), {'Schöne Lieder & Geschichten': URI})
            favorites.save('Schöne Lieder & Geschichten', URI)
            self.assertEqual(len(favorites.load()), 1)
            favorites.remove('Schöne Lieder & Geschichten')
            self.assertEqual(Favorites(path).load(), {})

    def test_malformed_file_is_preserved_on_save(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'favorites.yaml'
            for content in ('- not a mapping\n', 'Broken: [', 'A: not-a-playlist', 'true: null'):
                with self.subTest(content=content):
                    path.write_text(content, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        Favorites(path).save('New', URI)
                    self.assertEqual(path.read_text(encoding='utf-8'), content)

    def test_failed_replace_preserves_previous_favorites(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'favorites.yaml'
            favorites = Favorites(path)
            favorites.save('Original', URI)
            with patch.object(Path, 'replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    favorites.save('New', URI)
            self.assertEqual(favorites.load(), {'Original': URI})
            self.assertEqual(list(path.parent.iterdir()), [path])


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Config(self.directory.name)
        self.config.set_bool('plugins', 'spotify', 'enabled', value=True)
        self.plugin = Spotify('Spotify', self.config, queue.Queue(), queue.Queue())
        self.fake = FakeSoloist()
        patcher = patch('plapperkasten.plugins.spotify.spotify.subprocess.run', self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def events(self):
        events = []
        while not self.plugin._from_plugin.empty():
            events.append(self.plugin._from_plugin.get_nowait())
        return events

    def test_disabled_plugin_does_not_call_soloist(self):
        self.config.set_bool('plugins', 'spotify', 'enabled', value=False)
        plugin = Spotify('Spotify', self.config, queue.Queue(), queue.Queue())
        plugin.on_before_run()
        plugin.on_load_source(use='Spotify', key=URI)
        plugin.on_play()
        plugin.on_after_run()
        self.assertEqual(self.fake.commands, [])

    def test_loading_activates_local_device_and_reports_confirmed_playback(self):
        self.plugin.on_load_source(use='Spotify', key=LINK)
        self.assertEqual(self.fake.commands, [['activate'], ['play', URI]])
        self.assertTrue(self.plugin.is_busy())
        self.assertEqual(self.events()[-1].params['state'], 'Starting playback')
        self.plugin.on_tick()
        self.assertEqual(self.events()[-1].params,
                         {'state': 'Playing', 'track': 'A song', 'error': ''})

    def test_controls_and_busy_state_follow_the_selected_source(self):
        self.plugin.on_next()
        self.assertEqual(self.fake.commands, [])
        self.plugin.on_load_source(use='Spotify', key=URI)
        self.plugin.on_pause()
        self.plugin.on_tick()
        self.assertFalse(self.plugin.is_busy())
        self.plugin.on_toggle()
        self.plugin.on_tick()
        self.assertTrue(self.plugin.is_busy())
        self.plugin.on_next()
        self.plugin.on_previous()
        self.plugin.on_stop()
        self.assertIn(['next'], self.fake.commands)
        self.assertIn(['prev'], self.fake.commands)
        self.assertEqual(self.fake.commands[-2:], [['pause'], ['seek', '0']])
        self.plugin.on_load_source(use='Mpdclient', key='music.m3u')
        calls = list(self.fake.commands)
        self.plugin.on_play()
        self.plugin.on_toggle()
        self.plugin.on_next()
        self.assertEqual(self.fake.commands, calls)
        self.assertFalse(self.plugin.is_busy())

    def test_handover_does_not_pause_spotify_on_another_device(self):
        self.plugin.on_load_source(use='Spotify', key=URI)
        self.fake.snapshot['is_active'] = False
        self.fake.commands.clear()
        self.plugin.on_pause()
        self.plugin.on_load_source(use='Mpdclient', key='music.m3u')
        self.assertNotIn(['pause'], self.fake.commands)
        self.assertFalse(self.plugin.is_busy())

    def test_failures_release_busy_state_and_recover_on_next_poll(self):
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired('soloist', 3),
                        subprocess.CalledProcessError(3, 'soloist')):
            with self.subTest(failure=failure):
                self.plugin.on_load_source(use='Spotify', key=URI)
                self.fake.failure = failure
                self.plugin.on_tick()
                self.assertFalse(self.plugin.is_busy())
                self.assertEqual(self.events()[-1].params['state'], 'Unavailable')
                self.fake.failure = None
                self.plugin.on_tick()
                self.assertTrue(self.plugin.is_busy())
                self.assertEqual(self.events()[-1].params['error'], '')

    def test_invalid_status_and_input_do_not_crash_or_execute_input(self):
        self.plugin.on_load_source(use='Spotify', key=URI + '; bad-command')
        self.assertEqual(self.fake.commands, [])
        with patch('plapperkasten.plugins.spotify.spotify.subprocess.run',
                   return_value=Mock(stdout='[]')):
            self.plugin.on_tick()
        self.assertEqual(self.events()[-1].params['state'], 'Unavailable')

    def test_queue_reports_titles_and_artists_without_polling_on_every_tick(self):
        self.plugin.on_tick()
        data = json.loads(next(event.params['data'] for event in self.events()
                               if event.name == 'spotify_queue'))
        self.assertEqual(data['current']['name'], 'A song')
        self.assertEqual(data['upcoming'][0],
                         {'name': 'Next song', 'artist': 'An artist', 'uri': NEXT_URI})
        self.assertEqual(data['context'], 'Bedtime songs')
        queue_reads = sum(command[0] == 'queue' for command in self.fake.commands)
        self.plugin.on_tick()
        self.assertEqual(sum(command[0] == 'queue' for command in self.fake.commands), queue_reads)
        self.fake.snapshot['item']['uri'] = NEXT_URI
        self.plugin.on_tick()
        self.assertEqual(sum(command[0] == 'queue' for command in self.fake.commands), queue_reads + 1)

    def test_queue_failure_does_not_stop_confirmed_playback(self):
        self.plugin.on_load_source(use='Spotify', key=URI)
        def run(arguments, **options):
            if arguments[2] == 'queue':
                raise subprocess.TimeoutExpired('soloist', 3)
            return self.fake(arguments, **options)
        with patch('plapperkasten.plugins.spotify.spotify.subprocess.run', run):
            self.plugin.on_tick()
        self.assertTrue(self.plugin.is_busy())
        events = self.events()
        queue = json.loads(next(event.params['data'] for event in events
                                if event.name == 'spotify_queue'))
        self.assertIn('unavailable', queue['error'])
        self.assertEqual(events[-1].params['state'], 'Playing')

    def test_malformed_queue_is_reported_without_crashing_playback_poll(self):
        self.fake.queue = {'previous': 'invalid', 'upcoming': []}
        self.plugin.on_tick()
        events = self.events()
        data = json.loads(next(event.params['data'] for event in events
                               if event.name == 'spotify_queue'))
        self.assertTrue(data['error'])
        self.assertEqual(events[-1].params['state'], 'Ready')


class SpotifyWebTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = Config(self.directory.name)
        config.set_bool('plugins', 'spotify', 'enabled', value=True)
        config.set_str('plugins', 'server', 'hostname', value='127.0.0.1')
        config.set_int('plugins', 'server', 'port', value=0)
        self.outgoing = queue.Queue()
        self.server = Server('Server', config, queue.Queue(), self.outgoing)
        self.player = Spotify('Spotify', config, queue.Queue(), self.outgoing)
        self.fake = FakeSoloist()
        patcher = patch('plapperkasten.plugins.spotify.spotify.subprocess.run', self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.core = Plapperkasten()
        self.core._queues_to_plugins = {}
        self.core._busy_processes = 0
        for plugin in (self.server, self.player):
            name = plugin.get_name().lower()
            self.core._queues_to_plugins[name] = plugin._to_plugin
            for event in plugin.get_registered_events():
                self.core.register(event, name)
        self.server.on_before_run()
        self.addCleanup(self.server.on_after_run)

    def request(self, method='GET', path='/main', fields=None, body=None):
        connection = http.client.HTTPConnection(
            '127.0.0.1', self.server._server.server_address[1], timeout=2)
        try:
            connection.request(method, path, urlencode(fields) if fields is not None else body,
                               {'Content-Type': 'application/x-www-form-urlencoded'})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode('utf-8')
        finally:
            connection.close()

    def relay(self):
        for _ in range(20):
            changed = False
            while not self.outgoing.empty():
                # Even existing configs with an empty passthrough list work.
                self.core.process_event(self.outgoing.get_nowait(), [])
                changed = True
            for plugin in (self.server, self.player):
                while not plugin._to_plugin.empty():
                    event = plugin._to_plugin.get_nowait()
                    getattr(plugin, 'on_' + event.name)(*event.values, **event.params)
                    changed = True
            if not changed:
                return
        self.fail('Event routing did not settle')

    def test_save_play_and_remove_through_real_http_and_event_bus(self):
        status, headers, _ = self.request('POST', '/spotify',
                                         {'action': 'save', 'playlist': LINK, 'name': 'Bedtime'})
        self.assertEqual(status, 303)
        self.assertIn('spotify=saved', headers['Location'])
        self.assertTrue(self.outgoing.empty())
        favorites = Favorites(Path(self.directory.name) / 'spotify_favorites.yaml')
        self.assertEqual(favorites.load(), {'Bedtime': URI})
        _, _, page = self.request(path=headers['Location'].split('#')[0])
        self.assertIn('id="tab_2" checked', page)
        self.assertIn('Play Bedtime', page)
        self.assertIn('Playlist saved.', page)
        self.assertEqual(self.request('POST', '/spotify',
                                     {'action': 'play', 'favorite': 'Bedtime'})[0], 303)
        self.relay()
        self.assertIn(['play', URI], self.fake.commands)
        self.player.on_tick()
        self.relay()
        state = json.loads(self.request(path='/api/status')[2])
        self.assertEqual(state['spotify_state'], 'Playing')
        self.assertEqual(state['spotify_track'], 'A song')
        self.assertEqual(self.core._busy_processes, 1)
        self.request('POST', '/action', {'pause': 'Pause'})
        self.relay()
        self.player.on_tick()
        self.relay()
        self.assertEqual(self.core._busy_processes, 0)
        self.assertEqual(json.loads(self.request(path='/api/status')[2])['spotify_state'], 'Paused')
        self.request('POST', '/spotify', {'action': 'remove', 'favorite': 'Bedtime'})
        self.assertEqual(favorites.load(), {})

    def test_pasted_link_and_all_existing_transport_and_volume_events_are_routed(self):
        observer = queue.Queue()
        self.core._queues_to_plugins['observer'] = observer
        for event in ('load_source', 'play', 'pause', 'stop', 'next', 'previous', 'volume'):
            self.core.register(event, 'observer')
        self.assertEqual(self.request('POST', '/spotify',
                                     {'action': 'play', 'playlist': LINK, 'name': ''})[0], 303)
        self.relay()
        event = observer.get_nowait()
        self.assertEqual(event.params, {'use': 'Spotify', 'key': URI})
        for action in ('play', 'pause', 'stop', 'next', 'previous', '50'):
            self.assertEqual(self.request('POST', '/action', {action: action})[0], 200)
            self.relay()
            self.assertEqual(observer.get_nowait().name, 'volume' if action == '50' else action)

    def test_invalid_forms_are_rejected_before_dispatch_or_file_changes(self):
        for body in ('action=play&action=save&playlist=' + URI,
                     urlencode({'action': 'play', 'playlist': 'https://evil.test'}),
                     urlencode({'action': 'save', 'playlist': URI, 'name': ''}),
                     urlencode({'action': 'play', 'favorite': 'Missing'}),
                     urlencode({'action': 'remove', 'favorite': 'Missing', 'playlist': URI}),
                     urlencode({'action': 'shutdown', 'playlist': URI})):
            with self.subTest(body=body):
                self.assertEqual(self.request('POST', '/spotify', body=body)[0], 400)
                self.assertTrue(self.outgoing.empty())
        self.assertFalse((Path(self.directory.name) / 'spotify_favorites.yaml').exists())

    def test_names_tracks_and_errors_are_escaped_and_disabled_requests_rejected(self):
        self.request('POST', '/spotify',
                     {'action': 'save', 'playlist': URI, 'name': '<script> & "Music"'})
        self.server.on_spotify_status(state='Playing', track='<img src=x>', error='<b>Error</b>')
        _, _, page = self.request()
        self.assertIn('&lt;script&gt; &amp; &quot;Music&quot;', page)
        self.assertIn('&lt;img src=x&gt;', page)
        self.assertNotIn('<b>Error</b>', page)
        self.server._server.spotify_enabled = False
        self.assertEqual(self.request('POST', '/spotify',
                                     {'action': 'play', 'playlist': URI})[0], 503)
        self.assertTrue(self.outgoing.empty())

    def test_queue_fragment_and_track_selection_use_real_routing(self):
        self.player.on_tick()
        self.relay()
        status, headers, fragment = self.request(path='/spotify/queue')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('Next song', fragment)
        self.assertIn('An artist', fragment)
        self.assertIn('Play track', fragment)
        get_headers = headers
        status, headers, body = self.request('HEAD', '/spotify/queue')
        self.assertEqual(status, 200)
        self.assertEqual(body, '')
        self.assertEqual(headers['Content-Length'], get_headers['Content-Length'])
        state = json.loads(self.request(path='/api/status')[2])
        self.assertIn('spotify_queue_revision', state)
        self.assertNotIn('Next song', json.dumps(state))
        status, headers, _ = self.request('POST', '/spotify',
                                         {'action': 'track', 'track': NEXT_URI})
        self.assertEqual(status, 303)
        self.assertIn('#spotify_queue_section', headers['Location'])
        self.relay()
        self.assertIn(['play', NEXT_URI], self.fake.commands)
        self.assertTrue(self.player.is_busy())

    def test_queue_metadata_is_escaped_and_unknown_track_cannot_be_played(self):
        self.fake.queue['upcoming'][0]['item']['decorations']['identity']['name'] = '<img src=x onerror="bad()">'
        self.player.on_tick()
        self.relay()
        _, _, fragment = self.request(path='/spotify/queue')
        self.assertNotIn('<img src=x', fragment)
        self.assertIn('&lt;img src=x', fragment)
        self.assertTrue(self.outgoing.empty())
        for fields in ({'action': 'track', 'track': 'spotify:track:' + 'Z' * 22},
                       {'action': 'track', 'track': NEXT_URI + '; shutdown'},
                       {'action': 'track', 'track': NEXT_URI, 'favorite': 'Unrelated'},
                       {'action': 'play', 'playlist': URI, 'track': NEXT_URI}):
            with self.subTest(fields=fields):
                self.assertEqual(self.request('POST', '/spotify', fields)[0], 400)
                self.assertTrue(self.outgoing.empty())


if __name__ == '__main__':
    unittest.main()
