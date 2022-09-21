#!/usr/bin/env python3
"""Structure for events as the basis for plugins to communicate."""

from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)


class Event():
    """An item representing an event.

    Attributes:
        name: The name of the event.
        values: Values represented by this item.
        parameters: Parameters represented by this item.
    """
    __slots__ = ['name', 'values', 'params']

    def __init__(self,
                 name: str,
                 *values: str,
                 **params: str) -> None:
        """Initialises variables from parameters or KeyMapItem.

        Args:
            name: The name of the event.
            *values: A list of values.
            **parameters: A dictionary of parameters.
        """
        self.name: str = name
        self.values: list[str] = list(values) if values else []
        self.params: dict[str, str] = params if params else {}
