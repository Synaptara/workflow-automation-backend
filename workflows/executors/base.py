class BaseExecutor:
    """Every action executor (slack, trello, payment, ...) implements this."""

    def execute(self, config: dict, context: dict) -> dict:
        raise NotImplementedError
