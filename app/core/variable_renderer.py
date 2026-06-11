import re
from typing import Any


_VARIABLE_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def render_variables(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        matches = list(_VARIABLE_PATTERN.finditer(value))
        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            name = matches[0].group(1).strip()
            return variables.get(name, value)

        def replace(match: re.Match[str]) -> str:
            name = match.group(1).strip()
            return str(variables[name]) if name in variables else match.group(0)

        return _VARIABLE_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: render_variables(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render_variables(item, variables) for item in value]
    return value
