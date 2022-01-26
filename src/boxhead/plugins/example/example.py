#!/usr/bin/env python3

from boxhead import config as boxhead_config
from boxhead import event as boxhead_event
from boxhead import plugin
from boxhead.boxheadlogging import boxheadlogging

logger: boxheadlogging.BoxHeadLogger = boxheadlogging.get_logger(__name__)

class Example(plugin.Plugin):
    def on_init(self, config: boxhead_config.Config) -> None:
        logger.debug('Hey there! :)')

    def on_tick(self) -> None:
        logger.debug('I\'m doing something immensely useful.')
