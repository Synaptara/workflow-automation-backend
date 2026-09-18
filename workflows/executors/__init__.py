from .base import BaseExecutor

EXECUTOR_REGISTRY = {}


def register(key):
    def wrapper(cls):
        EXECUTOR_REGISTRY[key] = cls()
        return cls
    return wrapper
