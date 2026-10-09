class BaseExecutor:
    def execute(self, app_event: str, config: dict, context: dict) -> dict:
        raise NotImplementedError("Executors must implement the execute method.")

    def match_ingress_event(
        self, app_event: str, event_type: str, payload: dict, step_config: dict
    ) -> bool:
        """
        Evaluates if an incoming webhook payload matches this trigger step's configuration.
        Defaults to True unless overridden by specific integration logic.
        """
        return True
