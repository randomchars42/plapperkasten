#!/usr/bin/env python3.9
"""BoxHead."""

import argparse
#import importlib
import multiprocessing
#import os
#import pkgutil
#import pkg_resources
import queue
import signal
#import sys
import threading

from boxhead import config as boxhead_config
from boxhead import plugin
from boxhead.boxheadlogging import boxheadlogging

logger: boxheadlogging.BoxHeadLogger = boxheadlogging.get_logger(__name__)

class BoxHead:
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
        _logger_thread: Thread that does the work of logging for all
            processes.
        _logger_queue: Queue to the logger thread.
        _events: Events and their subscribers.
    """

    def get_queue_to_plugin(self,
                            to_whom: str,
                            create: bool = True) -> multiprocessing.Queue:
        """Returns a queue that leads to the given plugin.

        Args:
            to_whom: The name of the plugin the queue leads to.
            create: Create a queue if necessary.

        Returns:
            A Queue-object to the plugin

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
            self._queue_from_plugins: multiprocessing.Queue = multiprocessing.Queue(
            )

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
            logger.error('no such subscriber (%s) for event %s', who,
                               event)

    def unregister_from_all(self, who: str) -> None:
        """Unregisters a plugin from all events it has subscribed to.

        Args:
            who: The name of the plugin to unregister.
        """

        events: dict[str, list[str]] = self.get_events()

        for subscribers in events.values():
            if who in subscribers:
                subscribers.remove(who)

    def emit(self, event: str) -> None:
        """Emit an event to all its subscribers.

        Args:
            event: The name of the event.
        """

        subscribers: list[str] = self.get_subscribers(event)

        if len(subscribers) == 0:
            logger.debug('trying to dispatch %s but no one is listening',
                               event)
            return

        for subscriber in subscribers:
            try:
                logger.debug('emitting %s for %s', event, subscriber)
                self.get_queue_to_plugin(subscriber, False).put(event)
            except KeyError:
                # a name has been registered which does not belong to a plugin
                logger.error('no queue to subscriber %s', subscriber)
                self.unregister_from_all(subscriber)
                self.delete_queue_to_plugin(subscriber)
            except ValueError:
                # the queue has been closed / damaged so do not use it anymore
                self.unregister_from_all(subscriber)
                self.delete_queue_to_plugin(subscriber)
                logger.error('queue to %s has been destroyed',
                                   subscriber)

    def on_interrupt(self, signal_num: int, frame: object) -> None:
        #pylint: disable=unused-argument
        """Stop the running process on interrupt.

        Args:
            signal_num: The signal number that was sent to the process.
            frame: The current stack frame.
        """

        self.emit('terminate')
        self._terminate_signal = True

    def start_logging(self) -> None:
        """Create thread and a queue to log from multiple processes.
        """

        self._logger_queue: multiprocessing.Queue = boxheadlogging.get_queue()

        self._logger_thread: threading.Thread = threading.Thread(
            target=self.run_logger, args=(self._logger_queue, ))
        self._logger_thread.start()

        # Some details on subtleties:
        # https://fanchenbao.medium.com/python3-logging-with-multiprocessing-f51f460b8778

    def stop_logging(self) -> None:
        """Stop the logging thread."""

        self._logger_queue.put(None)

    def run_logger(self, record_queue: multiprocessing.Queue) -> None:
        """Logs all records sent through the queue.

        Runs in its own thread so it doesn't block the main thread.

        Args:
            queue: The queue that is used by the QueueFileHandler.
        """

        thread_logger: boxheadlogging.BoxHeadLogger = boxheadlogging.get_logger(
                'logging_thread')
        while True:
            # TODO: add  type
            record = record_queue.get(True)
            if record is None:
                break
            thread_logger.handle(record)

    def run(self, config: boxhead_config.Config) -> None:
        """Run the application.

        Args:
            verbosity: A value between 0 (ERROR) and 3 (DEBUG).
        """
        signal.signal(signal.SIGINT, self.on_interrupt)
        signal.signal(signal.SIGTERM, self.on_interrupt)

        self._terminate_signal = False

        self.start_logging()

        processes: list[plugin.Plugin] = []
        for i in range(0, 3):
            processes.append(
                plugin.Plugin(str(i), self, self.get_queue_to_plugin(str(i)),
                              self.get_queue_from_plugins()))
            self.register('terminate', str(i))
            logger.debug('starting process %s', i)
            processes[i].start()

        while not self._terminate_signal:
            try:
                event: object = self._queue_from_plugins.get(True, 0.1)
                logger.debug('recieved %s', event)
            except queue.Empty:
                pass
            except ValueError:
                logger.error('queue from plugins closed')

        for i in range(0, 3):
            processes[i].join()

        self.stop_logging()
        self._logger_thread.join()


def main() -> None:
    """Reads cli arguments and runs the main loop."""

    verbosity: int = 3
    levels: list[str] = ['ERROR', 'WARNING', 'INFO', 'DEBUG']
    #log.config['handlers']['console']['level'] = levels[verbosity] # type: ignore
    #log.config['handlers']['file']['level'] = levels[verbosity] # type: ignore

    config = boxhead_config.Config()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-o', '--options',
        help='arbitrary configuration options as could be found in the ' +
            'ini-file \n' +
            'formatted like SECTION1.option1=val1@@' +
            'SECTION2.option4=val2@@... \n' +
            'e.g., Soundcontrol.max_volume=60@@' +
            'InputUSBRFID.device=/dev/event0 \n' +
            '"@@" serves as a separator',
        action='store',
        default='',
        type=str)
    parser.add_argument(
        '-d', '--user_dir',
        help='the directory where your config.ini, eventmap, etc. is stored',
        action='store',
        type=str,
        default='')
    parser.add_argument(
        '-v', '--verbosity',
        help='increase verbosity',
        action='count',
        default=0)

    args = parser.parse_args()

    if not args.options == '':
        for option in args.options.split('@@'):
            try:
                section, rest = option.split('.', 1)
                option, value = rest.split('=', 1)
                config.set(section, option, value)
            except ValueError:
                print(f'did not understand option "{option}"')

    if not args.user_dir == '':
        config.set('Paths', 'user_dir', args.user_dir)

    boxhead: BoxHead = BoxHead()
    boxhead.run(config)

if __name__ == '__main__':
    main()
