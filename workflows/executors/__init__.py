from .base import BaseExecutor

EXECUTOR_REGISTRY = {}


def register(key):
    def wrapper(cls):
        EXECUTOR_REGISTRY[key] = cls()
        return cls
    return wrapper


# These imports MUST come after `register` is defined above — each module's
# @register("...") decorator runs at import time and needs it to exist.
# Without this, EXECUTOR_REGISTRY stays empty no matter what action_key you use.
from . import slack   # noqa: E402,F401
from . import trello  # noqa: E402,F401
from . import email
from . import http_request
from . import discord
from . import google_sheets