from typing import Any


def json_values_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON values without treating booleans as numbers."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected

    if isinstance(actual, dict) or isinstance(expected, dict):
        if not isinstance(actual, dict) or not isinstance(expected, dict):
            return False
        return actual.keys() == expected.keys() and all(
            json_values_equal(actual[key], expected[key]) for key in actual
        )

    if isinstance(actual, list) or isinstance(expected, list):
        if not isinstance(actual, list) or not isinstance(expected, list):
            return False
        return len(actual) == len(expected) and all(
            json_values_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )

    return actual == expected
