#!/usr/bin/env python3.9
import logging
import logging.config

import time

import signal
from multiprocessing import Queue
from queue import Empty

from .log import log
from boxhead import plugin

logger = logging.getLogger(__name__)

class BoxHead:
    """Main unit for controlling the box.

    Loads the config:
    * from 'config/config.ini' (do not edit this)
    * from 'USER_DIRECTORY/config.ini' (use this file to overwrite values from config/config.ini)
    * from the command line if passed in

    Loads all plugins (python packages):
    * core plugins from 'plugins/'
    * user plugins from 'USER_DIRECTORY/plugins/'
    """

    def get_queue_to_plugin(self, to_whom: str, create: bool = True) -> Queue:
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
            self._queues_to_plugins: dict[str, Queue] = {}

        if create and not to_whom in self._queues_to_plugins.keys():
            self._queues_to_plugins[to_whom] = Queue()

        return self._queues_to_plugins[to_whom]

    def delete_queue_to_plugin(self, to_whom: str) -> None:
        """Deletes the queue that leads to the plugin.

        Args:
            to_whom: The name of the plugin the queue leads to.
        """

        if not hasattr(self, '_queues_to_plugins'):
            logger.error('no queues to plugins initialised yet')
            return

        if to_whom in self._queues_to_plugins.keys():
            del self._queues_to_plugins[to_whom]

        else:
            logger.error('no queue to plugin {}'.format(to_whom))

    def get_queue_from_plugins(self) -> Queue:
        """Get the one queue recieving input from all plugins.

        Creates the queue if necessary.

        Returns:
            The queue recieving input from all plugins.
        """

        if not hasattr(self, '_queue_from_plugins'):
            self._queue_from_plugins: Queue = Queue()

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
            logger.error('no such subscriber ({}) for event {}'.format(who, event))

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
            logger.debug('trying to dispatch {} but no one is listening'.format(
                event))
            return

        for subscriber in subscribers:
            try:
                logger.debug('emitting {} for {}'.format(event, subscriber))
                queue = self.get_queue_to_plugin(subscriber, False)
                queue.put(event)
            except KeyError:
                # a name has been registered which does not belong to a plugin
                logger.error('no queue to subscriber {}'.format(subscriber))
                self.unregister_from_all(subscriber)
                self.delete_queue_to_plugin(subscriber)
            except ValueError:
                # the queue has been closed/ damaged so do not use it anymore
                self.unregister_from_all(subscriber)
                self.delete_queue_to_plugin(subscriber)
                logger.error('queue to {} has been destroyed'.format(subscriber))

    def on_interrupt(self, signal_num: int, frame: object) -> None:
        """Stop the running process on interrupt.

        Args:
            signal_num: The signal number that was sent to the process.
            frame: The current stack frame.
        """

        self.emit('terminate')
        self._terminate_signal = True

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.on_interrupt)
        signal.signal(signal.SIGTERM, self.on_interrupt)

        self._terminate_signal = False

        processes = []
        for i in range(0,3):
            processes.append(plugin.Plugin(
                str(i),
                self,
                self.get_queue_to_plugin(str(i)),
                self.get_queue_from_plugins()))
            self.register('terminate', str(i))
            logger.debug('starting process {}'.format(i))
            processes[i].start()

        while not self._terminate_signal:
            try:
                event: object = self._queue_from_plugins.get(True, 0.1)
                logger.debug('recieved {}'.format(event))
            except Empty:
                pass
            except ValueError:
                logger.error('queue from plugins closed')

        for i in range(0,3):
            processes[i].join()


def main() -> None:
    """Reads cli arguments, configures logging and runs the main loop.
    """
    logging.config.dictConfig(log.config)
    boxhead: BoxHead = BoxHead()
    boxhead.run()


if __name__ == '__main__':
    main()
