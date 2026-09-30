class BaseExecutor:
    def execute(self, app_event: str, config: dict, context: dict) -> dict:
        raise NotImplementedError("Executors must implement the execute method.")
