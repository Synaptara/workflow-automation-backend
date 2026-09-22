"""
Structured condition config shape:
{"field": "budget", "operator": ">", "value": 5000}
"field" supports dot-notation into the trigger payload, e.g. "customer.plan"
"""

OPERATORS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "contains": lambda a, b: b in a if a is not None else False,
}


def _resolve(field: str, context: dict):
    value = context
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def evaluate_condition(config: dict, context: dict) -> bool:
    field = config.get("field", "")
    operator = config.get("operator", "==")
    expected = config.get("value")

    op = OPERATORS.get(operator)
    if op is None:
        raise ValueError(f"Unsupported operator: {operator}")

    actual = _resolve(field, context)

    if operator in (">", "<", ">=", "<="):
        try:
            actual = float(actual)
            expected = float(expected)
        except (TypeError, ValueError):
            return False

    return bool(op(actual, expected))
