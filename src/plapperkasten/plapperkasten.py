#!/usr/bin/env python3.9
"""Plapperkasten."""

import argparse
import importlib
import logging
import multiprocessing
import os
import pathlib
import pkg_resources
import queue
import signal
import sys

from types import ModuleType

from plapperkasten import config as plkconfig
from plapperkasten import event as plkevent
from plapperkasten import eventmap
from plapperkasten import plugin as plkplugin
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Plapperkasten:
    """Main unit for controlling the box.

    Loads the config:
    * from 'config/config.ini' (do not edit this)
    * from 'USER_DIRECTORY/config.ini' (use this file to overwrite
      values from config/config.ini)
    * from the command line if passed in

    Loads all plugins (python packages):
    * core plugins from 'plugins/'
    * user plugins from 'USER_DIRECTORY/plugins/'

    Handles logging:
    Logging is done by its own thread.

    Attributes:
        _queues_to_plugin: Queues to signal to each plugin.
        _queue_from_plugin: Queue to get input from all plugins.
        _logger_queue: Queue to the logger thread.
        _events: A dictionary of events and their subscribers.
        _plugins: A list of plugin.
        _eventmap: A map of raw events and events to emit.
        _shutdown_signal: Shutdown after all processes stopped?
        _busy_processes: A counter of processes that mark themselves
            as busy at the moment and thereby inhibit actions that
            may be triggered by the programme being idle and waiting
            for input, e.g. auto-shutdown.
    """

    def run(self, config: plkconfig.Config) -> None:
        """Run the application.

        Args:
            config: The configuration.
        """
        signal.signal(signal.SIGINT, self.on_interrupt)
        signal.signal(signal.SIGTERM, self.on_interrupt)

        self._busy_processes: int = 0
        self._terminate_signal: bool = False
        self._shutdown_signal: bool = False

        self.start_logging()

        logger.debug('this is plapperkasten running with pid %s', os.getpid())

        passthrough_events: list[str] = config.get_list_str('core',
                                                            'events',
                                                            'passthrough',
                                                            default=[])

        self._plugins: list[plkplugin.Plugin] = []

        self.load_plugins(config)

        for plugin in self._plugins:
            logger.debug('starting process %s', plugin.get_name())
            plugin.start()

        self._eventmap: eventmap.EventMap = eventmap.EventMap(config)

        self.emit('finished_loading')

        self.all_idle()

        if len(self._plugins) > 0:
            while not self._terminate_signal:
                try:
                    event: plkevent.Event = self._queue_from_plugins.get(
                        True, 0.1)
                    logger.debug('recieved %s', event.name)
                    self.process_event(event, passthrough_events)
                except queue.Empty:
                    pass
                except ValueError:
                    logger.error('queue from plugins closed')

        logger.debug('exited main loop')

        for plugin in self._plugins:
            plugin.join()

        logger.debug('all plugin processes stopped')

        self.stop_logging()
        self._logger.join()

        self.shutdown(
            config.get_int('core', 'system', 'shutdown_time', default=1),
            config.get_bool('core', 'system', 'debug', default=False))

    def load_plugins(self, config: plkconfig.Config) -> None:
        """Triggers a (re-)scan of the plugin directories.

        Tries to load all packages in the plugin directories as plugin.

        There are two directories which may hold plugins:
        * the core plugins reside under `./plugins`
        * the user may provide plugins in the user directory (default:
          `/~/.config/plapperkasten/plugins`)

        Loads the class `Greatplugin` (first letter uppercase) from
        file `/PATH/TO/PLUGINS/greatplugin/greatplugin.py`and stores
        the object under `_plugins['Greatplugin']`.

        Args:
            config: The configuration to get the paths.
        """

        self._load_plugins(
            pathlib.Path(
                pkg_resources.resource_filename(
                    __name__,
                    config.get_str('core',
                                   'paths',
                                   'plugins',
                                   default='plugins'))),
            config.get_list_str('core', 'plugins', 'blacklist', default=[]),
            config)

        self._load_plugins(
            pathlib.Path(
                config.get_str('core',
                               'paths',
                               'user_directory',
                               default='~/.config/plapperkasten'),
                config.get_str('core', 'paths', 'plugins',
                               default='plugins')).expanduser().resolve(),
            config.get_list_str('core', 'plugins', 'blacklist', default=[]),
            config)

    def _load_plugins(self, path: pathlib.Path, blacklist: list[str],
                      config: plkconfig.Config) -> None:
        """Gathers all packages located under path as plugins.

        Expect the main module of the plugin package to be named
        like the package, e.g.:

        * plugin name: myplugin
        * package name: myplugin (PATH/TO/myplugin/)
        * main module in: myplugin.py (PATH/TO/myplugin/myplugin.py)

        Expect the class of the plugin to be a descendant of
        `plapperkasten.plugin.Plugin` and to be named like the package but
        with the first letter uppercase, e.g.:

        * classname: Myplugin

        Each plugin is instantiated and stored in `_plugins`.

        Ech plugin gets registered for the `terminate` event so its
        process may be stopped later on, e.g., on interrupt.

        Args:
            path: The path to scan for packages.
            blacklist: A list of plugins to ignore. Use the package
                name (all lowercase).
        """

        logger.debug('loading plugins from %s', path)

        sys.path.append(str(path))

        for file in path.glob('*'):
            name: str = file.name

            if name == '__pycache__' or not file.is_dir():
                continue

            if name.lower() in blacklist:
                logger.debug('blacklisted plugin: %s', name)
                continue

            # expect the main module of the plugin package to be named
            # like the package, i.e.,
            # plugin name: myplugin
            # -> package name: myplugin
            #       (PATH/TO/PLUGINS/myplugin/)
            # -> main module in: myplugin.py
            #       (PATH/TO/PLUGINS/myplugin/myplugin.py)
            try:
                module: ModuleType = importlib.import_module(f'{name}.{name}')
            except ModuleNotFoundError:
                logger.error('could not import plugin %s', name)
                continue
            # expect the class of the plugin to be a descendant of
            # plapperkasten.plugin.Plugin and to be named like the package but with
            # the first letter uppercase, i.e.,
            # classname: Myplugin
            classname: str = name[0].upper() + name[1:]

            try:
                # load the plugin's config
                config.load_from_path(path / name / 'config.yaml')

                # load the plugin itself
                plugin: plkplugin.Plugin = getattr(module, classname)(
                    classname, config, self.get_queue_to_plugin(name),
                    self.get_queue_from_plugins())

                self._plugins.append(plugin)

                # register plugin for events
                for event in plugin.get_registered_events():
                    self.register(event, name)
                # `terminate` is mandatory
                self.register('terminate', name)
            except AttributeError:
                logger.error('failed to load module "%s" - class "%s" missing?',
                             name, classname)

        logger.info('plugins loaded from %s', path)

    def get_queue_to_plugin(self,
                            to_whom: str,
                            create: bool = True) -> multiprocessing.Queue:
        """Returns a queue that leads to the given plugin.

        Args:
            to_whom: The name of the plugin the queue leads to.
            create: Create a queue if necessary.

        Returns:
            A Queue-object to the plugin.

        Raises:
            KeyError: No queue has been created for that plugin and
            `create` is `False`.
        """

        if not hasattr(self, '_queues_to_plugins'):
            self._queues_to_plugins: dict[str, multiprocessing.Queue] = {}

        if create and not to_whom in self._queues_to_plugins:
            self._queues_to_plugins[to_whom] = multiprocessing.Queue()

        return self._queues_to_plugins[to_whom]

    def delete_queue_to_plugin(self, to_whom: str) -> None:
        """Deletes the queue that leads to the plugin.

        Args:
            to_whom: The name of the plugin the queue leads to.
        """

        if not hasattr(self, '_queues_to_plugins'):
            logger.error('no queues to plugins initialised yet')
            return

        if to_whom in self._queues_to_plugins:
            del self._queues_to_plugins[to_whom]

        else:
            logger.error('no queue to plugin %s', to_whom)

    def get_queue_from_plugins(self) -> multiprocessing.Queue:
        """Get the one queue recieving input from all plugins.

        Creates the queue if necessary.

        Returns:
            The queue recieving input from all plugins.
        """

        if not hasattr(self, '_queue_from_plugins'):
            self._queue_from_plugins: multiprocessing.Queue =  \
                    multiprocessing.Queue()

        return self._queue_from_plugins

    def get_events(self) -> dict[str, list[str]]:
        """Returns a dict with all registered events as keys.

        Creates the dict if necessary.

        Returns:
            A dicitonary with all events as keys and a list of plugins
            that are registered for this event as values.
        """

        if not hasattr(self, '_events'):
            self._events: dict[str, list[str]] = {}

        return self._events

    def get_subscribers(self, event: str) -> list[str]:
        """Returns a list of subscribers for a given event.

        Creates and returns an empty list if the event has not yet been
        created.

        Args:
            event: The name of the event to get subscribers for.

        Returns:
            A list of plugins that want to be notified.
        """

        events: dict[str, list[str]] = self.get_events()

        if not event in events:
            events[event] = []

        return events[event]

    def register(self, event: str, who: str, exclusive: bool = False) -> None:
        """Registers a plugin to be notified at an event.

        Args:
            event: The name of the event.
            who: The name of the plugin to notify.
            exclusive: Remove all other subscribers.
        """

        events: dict[str, list[str]] = self.get_events()

        if not event in self._events:
            events[event] = []

        if exclusive:
            events[event] = [who]
        else:
            if not who in events[event]:
                events[event].append(who)

    def unregister(self, event: str, who: str) -> None:
        """Removes a plugin from the group of subscribers.

        Args:
            event: The name of the event.
            who: The name of the plugin to unregister.
        """

        subscribers: list[str] = self.get_subscribers(event)

        if who in subscribers:
            subscribers.remove(who)
        else:
            logger.error('no such subscriber (%s) for event %s', who, event)

    def unregister_from_all(self, who: str) -> None:
        """Unregisters a plugin from all events it has subscribed to.

        Args:
            who: The name of the plugin to unregister.
        """

        events: dict[str, list[str]] = self.get_events()

        for subscribers in events.values():
            if who in subscribers:
                subscribers.remove(who)

    def emit(self, event: str, *values: str, **params: str) -> None:
        """Emit an event to all its subscribers.

        Args:
            event: The name of the event.
            *values: A list of values.
            **parameters: A dictionary of parameters.
        """

        subscribers: list[str] = self.get_subscribers(event)

        if len(subscribers) == 0:
            logger.debug('trying to dispatch %s but no one is listening',
                         event)
            return

        for subscriber in subscribers:
            try:
                logger.debug('emitting %s for %s', event, subscriber)
                self.get_queue_to_plugin(subscriber, False).put_nowait(
                    plkevent.Event(event, *values, **params))
            except queue.Full:
                logger.critical('queue to plugin %s full', subscriber)
            except KeyError:
                # a name has been registered which does not belong to a plugin
                logger.error('no queue to subscriber %s', subscriber)
                self.unregister_from_all(subscriber)
                self.delete_queue_to_plugin(subscriber)
            except ValueError:
                # the queue has been closed / damaged so do not use it anymore
                self.unregister_from_all(subscriber)
                self.delete_queue_to_plugin(subscriber)
                logger.error('queue to %s has been destroyed', subscriber)

    def on_interrupt(self, signal_num: int, frame: object) -> None:
        # pylint: disable=unused-argument
        """Stop the running process on interrupt.

        Args:
            signal_num: The signal number that was sent to the process.
            frame: The current stack frame.
        """

        self.emit('terminate')
        self._terminate_signal = True

    def on_shutdown(self, *values, **params) -> None:
        # pylint: disable=unused-argument
        """Prepare for shutdown.

        Args:
            values: Values that are attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """

        # notify plugins that shutdown is iminent
        self.emit('shutdown')
        # stop plugins
        self.emit('terminate')
        # switch from just exiting to shutdown
        self._shutdown_signal = True
        # end main loop
        self._terminate_signal = True

    def shutdown(self, shutdown_time: int, debug: bool) -> None:
        """Actual shutdown procedure when all processes have stopped.

        Args:
            shutdown_time: Time in minutes to set for shutdown.
        """

        if not self._shutdown_signal or not self._terminate_signal:
            # this should not be reached
            return

        if not debug:
            os.system(f'shutdown -P {str(shutdown_time)}')

    def start_logging(self) -> None:
        """Creates a process and a queue to collect log reports.

        This creates a process at the recieving end of the
        `logging.handlers.QueueHandler` that is configured by
        `plklogging`.
        """

        self._logger_queue: multiprocessing.Queue = plklogging.get_queue()

        # Do not use a `threading.Thread` here as it is suggested.
        # This would lead to random occurences of blocked threads on interrupt.
        # Details may be found here:
        # https://pythonspeed.com/articles/python-multiprocessing/
        # https://rachelbythebay.com/w/2011/06/07/forked/
        # https://rachelbythebay.com/w/2014/08/16/forkenv/
        self._logger: multiprocessing.Process = multiprocessing.Process(
            target=self.run_logger, args=(self._logger_queue, ))
        self._logger.start()

    def stop_logging(self) -> None:
        """Stop the logging thread."""

        self._logger_queue.put(None)

    def run_logger(self, record_queue: multiprocessing.Queue) -> None:
        """Logs all records sent through the queue.

        Runs in its own thread so it doesn't block the main thread.

        Args:
            queue: The queue that is used by the QueueFileHandler.
        """

        signal.signal(signal.SIGINT, lambda signal_num, frame: ...)
        signal.signal(signal.SIGTERM, lambda signal_num, frame: ...)
        thread_logger: plklogging.PlkLogger = plklogging.get_logger(
            'logging_thread')
        while True:
            record: logging.LogRecord = record_queue.get(True)
            if record is None:
                logger.debug('stopping logging thread')
                break
            thread_logger.handle(record)

    def process_event(self, event: plkevent.Event,
                      passthrough: list[str]) -> None:
        """Process incoming events.

        Events named 'raw' will be looked up in the event map. All other
        events will be emitted if allowd by config.events.passthrough.

        Args:
            event: The event to process.
            passthrough: List of events, that  wil be re-emitted if
                they are recieved.
        """
        # events will be processed and reemitted
        # "raw"-events will be looked up on the event map and a new
        # event will be created
        new: bool = False

        if event.name == 'raw':
            event = self._eventmap.get_event(event.values[0])
            new = True

        if event.name == '':
            # empty event
            # occurs e.g. if the key is not found
            return

        if hasattr(self, 'on_' + event.name):
            # the way of the main process to respond to events
            # just check if an `on_EVENT` function is defined
            getattr(self, 'on_' + event.name)(*event.values, **event.params)

        if event.name in ('busy', 'idle'):
            # those case are taken care of by `on_idle` and `on_busy` so
            # return
            return

        if new or not event.name in passthrough:
            self.emit(event.name, *event.values, **event.params)

    def on_busy(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Triggered if a plugin gets busy, increases the counter.

        Args:
            values: Values that are attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """
        self._busy_processes += 1

        if self._busy_processes == 1:
            self.emit('busy')

    def on_idle(self, *values: str, **params: str) -> None:
        # pylint: disable=unused-argument
        """Triggered if a plugin switches to idle.

        Decreases the counter of busy processes and triggers a
        reevaluation if the whole programme is idle.

        Args:
            values: Values that are attached to the event (ignored).
            params: Parameters attached to the event (ignored).
        """

        if self._busy_processes == 0:
            logger.error('more processes became idle than said were busy')

        self._busy_processes -= 1

        self.all_idle()

    def all_idle(self) -> bool:
        """True if this process and all of the plugins are idle."""
        if self._busy_processes > 0:
            return False

        self.emit('idle')

        return True



def main() -> None:
    """Reads cli arguments and runs the main loop."""

    config = plkconfig.Config()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-o',
        '--options',
        help='arbitrary configuration options as could be found in the ' +
        'yaml file \nformatted like path.to.option1=val1@@' +
        'path2.to.option2=val2@@... \n' +
        'e.g., plugins.soundcontrol.max_volume=60@@' +
        'plugins.inputrfidusb.device=/dev/event0 \n' +
        '"@@" serves as a separator',
        action='store',
        default='',
        type=str)
    parser.add_argument(
        '-d',
        '--user_dir',
        help='the directory where your config.ini, eventmap, etc. is stored',
        action='store',
        type=str,
        default='')
    parser.add_argument('-v',
                        '--verbosity',
                        help='increase verbosity',
                        action='count',
                        default=0)

    args = parser.parse_args()

    levels: list[str] = ['ERROR', 'WARNING', 'INFO', 'DEBUG']
    # there are only levels 0 to 3
    # everything else will cause the index to be out of bounds
    verbosity_level: int = min(args.verbosity, 3)
    if config.get_bool('core', 'system', 'debug', default=False):
        verbosity_level = 3
    root_logger: plklogging.PlkLogger = plklogging.get_logger()
    root_logger.setLevel(levels[verbosity_level])
    if levels[args.verbosity] == 'DEBUG':
        config.set_bool('core', 'system', 'debug', value=True, target='input')

    if not args.options == '':
        for option in args.options.split('@@'):
            try:
                rest: str = ''
                value: str = ''
                rest, value = option.split('=', 1)
                path: list[str] = rest.split('.')
                config.set_str(*path, value=value)
            except ValueError:
                logger.error('did not understand option "%s"', option)

    if not args.user_dir == '':
        config.set_str('core', 'paths', 'user_directory', value=args.user_dir)

    plapperkasten: Plapperkasten = Plapperkasten()
    plapperkasten.run(config)


if __name__ == '__main__':
    main()
