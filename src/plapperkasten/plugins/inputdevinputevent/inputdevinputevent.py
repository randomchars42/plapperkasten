#!/usr/bin/env python3
"""Recieve input from `/dev/input/eventX`.
"""

import selectors

import evdev

from plapperkasten import config as plkconfig
from plapperkasten import plugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Inputdevinputevent(plugin.Plugin):
    """Gather input from ``/dev/input/eventX`.

    Attributes:
        _devices: List of devices to read input from.
        _keys: A string to map key numbers to letters /
            numbers.
        _selector: The selector that handles reading the
            devices.
        _current_input: Dictionary of strings. One string for
            each device, used to gather input until ENTER is
            pressed.
    """

    def on_init(self, config: plkconfig.Config) -> None:
        """Retrieve the names of the devices to listen to.

        Args:
            config: The configuration.
        """

        self._tick_interval = 0

        self._device_names: list[str] = config.get_list_str(
            'plugins', 'inputdevinputevent', 'devices', default=[])
        self._keys: str = config.get_str('plugins',
                                          'inputdevinputevent',
                                          'layout',
                                          default='')

    def on_before_run(self) -> None:
        """Initiate input devices.

        Cannot by done in `on_init` as those seem to get copied into the
        process where the copies are closed, but the original device
        objects remain open.
        """

        self._devices: list[evdev.InputDevice] = []
        self._selector: selectors.DefaultSelector = selectors.DefaultSelector()
        self._current_input: dict[str, str] = {}

        for dev in map(evdev.InputDevice, self._device_names):
            self._devices.append(dev)
            self._selector.register(dev, selectors.EVENT_READ)
            self._current_input[dev.name] = ''

    def on_tick(self) -> None:
        """Query all input devices and add their respective input."""
        # pylint: disable=unused-variable
        for key, mask in self._selector.select(0.2):
            device: object = key.fileobj
            if isinstance(device, evdev.InputDevice):
                for event in device.read():
                    if event.type == 1 and event.value == 1:
                        if evdev.ecodes.keys[event.code] == 'KEY_ENTER':
                            if not self._current_input[device.name] == '':
                                self.send_to_main(
                                    'raw', self._current_input[device.name])
                                self._current_input[device.name] = ''
                        else:
                            self._current_input[device.name] += self._keys[
                                event.code]

    def on_after_run(self) -> None:
        """Close and free up devices."""
        super().on_after_run()
        for dev in self._devices:
            dev.close()
        self._devices.clear()
