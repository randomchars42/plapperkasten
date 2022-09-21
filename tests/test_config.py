#!/usr/bin/env python3
"""Tests for plapperkasten.config."""

import unittest

from plapperkasten import config as plkconfig


class TestConfig(unittest.TestCase):
    """Test the Config class."""

    def setUp(self):
        # empty config
        self.config: plkconfig.Config = plkconfig.Config()

    def test_get(self):
        self.assertRaises(ValueError,
                          self.config.get,
                          'core',
                          'paths',
                          default='a')  # path too short

    def test_get_x(self):
        self.assertRaises(ValueError,
                          self.config.get_int,
                          'core',
                          'system',
                          'shutdown_time',
                          default='a')  # invalid default type
        # expect default value
        self.assertEqual(
            self.config.get_str('bla', 'blubb', 'meuf', default='a'), 'a')

    def test_set_x(self):
        self.config.set_str('bla', 'blubb', 'meuf', value='b')
        self.assertEqual(
            self.config.get_str('bla', 'blubb', 'meuf', default='a'), 'b')

if __name__ == '__main__':
    unittest.main()
