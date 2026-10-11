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

    def fetch_test_data(self, app_event: str, config: dict) -> dict:
        """
        Fetches live test data for the Workflow Builder UI.
        If an executor doesn't implement this, the backend raises NotImplementedError,
        and the frontend falls back to the mock schema.
        """
        raise NotImplementedError(
            "Live fetching is not supported for this integration."
        )
