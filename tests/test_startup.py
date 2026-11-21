"""Startup sound waits for confirmed output volume, including slow backends."""

import queue
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from plapperkasten.config import Config
from plapperkasten.event import Event
from plapperkasten.plapperkasten import Plapperkasten
from plapperkasten.plugins.soundeffects.soundeffects import Soundeffects
from plapperkasten.plugins.soundpwwp.soundpwwp import Soundpwwp


class StartupVolumeTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = Config(self.directory.name)
        config.set_int('plugins', 'soundpwwp', 'max', value=50)
        config.set_int('plugins', 'soundpwwp', 'startup_volume', value=30)
        incoming, self.outgoing = queue.Queue(), queue.Queue()
        incoming.put(Event('terminate'))
        self.backend = Soundpwwp('Soundpwwp', config, incoming, self.outgoing)
        self.volume = 80
        self.ignore_writes = False
        self.order = []

        def wpctl(*arguments):
            if '--help' in arguments:
                return 'Usage: --limit LIMIT'
            if arguments[0] == 'get-volume':
                return f'Volume: {self.volume / 100:.2f}'
            if arguments[0] == 'set-volume':
                level = int(arguments[-1].removesuffix('%'))
                self.order.append(('volume', level))
                if not self.ignore_writes:
                    self.volume = level
            return ''

        self.backend.wpctl = wpctl
        self.backend.query_sinks = self.backend.query_current_sink = Mock()
        self.backend.toggle_sink = Mock(side_effect=lambda _: self.order.append(('output',)))
        self.effects = Soundeffects('Soundeffects', config, queue.Queue(), queue.Queue())
        self.effects.play_sound = Mock(side_effect=lambda _: self.order.append(('sound', self.volume)))
        self.core = Plapperkasten()
        self.core._starting_plugins = {'soundpwwp'}
        self.core._busy_processes = 0

        def emit(name, *values, **params):
            if name == 'finished_loading':
                self.effects.on_finished_loading()

        self.core.emit = Mock(side_effect=emit)

    def initialize_backend(self):
        with patch('plapperkasten.plugin.signal.signal'):
            self.backend.run()
        while not self.outgoing.empty():
            self.core.process_event(self.outgoing.get_nowait(), [])

    def test_sound_waits_for_output_selection_and_confirmed_thirty_percent(self):
        self.core.process_event(Event('plugin_ready', 'soundeffects'), [])
        self.effects.play_sound.assert_not_called()
        self.initialize_backend()
        self.assertEqual(self.order, [('output',), ('volume', 50),
                                     ('volume', 30), ('sound', 30)])
        self.effects.play_sound.assert_called_once_with('ready')

    def test_startup_level_respects_lower_maximum(self):
        self.backend._max_volume = 20
        self.initialize_backend()
        self.assertEqual(self.order[-1], ('sound', 20))

    def test_failed_volume_confirmation_cannot_trigger_ready_sound(self):
        self.ignore_writes = True
        self.core.process_event(Event('plugin_ready', 'soundeffects'), [])
        with self.assertRaisesRegex(RuntimeError, 'startup volume'):
            self.initialize_backend()
        self.assertTrue(self.outgoing.empty())
        self.effects.play_sound.assert_not_called()

    def test_duplicate_and_unknown_readiness_do_not_play_the_sound_twice(self):
        self.initialize_backend()
        for name in ('unknown', 'soundeffects', 'soundpwwp', 'soundeffects'):
            self.core.process_event(Event('plugin_ready', name), [])
        self.effects.play_sound.assert_called_once_with('ready')

    def test_missing_mixer_state_cannot_be_mistaken_for_the_volume_cap(self):
        self.backend._max_volume = 30
        self.backend.wpctl = Mock(return_value='')
        with self.assertRaisesRegex(RuntimeError, 'startup volume'):
            self.initialize_backend()
        self.assertTrue(self.outgoing.empty())
        self.effects.play_sound.assert_not_called()


if __name__ == '__main__':
    unittest.main()
