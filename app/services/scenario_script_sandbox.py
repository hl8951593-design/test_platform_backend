import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any


MAX_SCRIPT_BYTES = 100_000
MAX_PAYLOAD_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 1_000_000


_PYTHON_RUNNER = r'''
import ast
import json
import sys

payload = json.loads(sys.stdin.read())
tree = ast.parse(payload["code"], mode="exec")
blocked = (
    ast.Import, ast.ImportFrom, ast.Attribute, ast.FunctionDef, ast.AsyncFunctionDef,
    ast.ClassDef, ast.Lambda, ast.With, ast.AsyncWith, ast.Try, ast.Raise,
    ast.Global, ast.Nonlocal, ast.Delete, ast.Await, ast.Yield, ast.YieldFrom,
)
allowed_calls = {
    "abs": abs, "bool": bool, "dict": dict, "enumerate": enumerate,
    "float": float, "int": int, "len": len, "list": list, "max": max,
    "min": min, "range": range, "round": round, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "zip": zip,
}
for node in ast.walk(tree):
    if isinstance(node, blocked):
        raise ValueError(f"Python syntax is not allowed: {type(node).__name__}")
    if isinstance(node, ast.Name) and node.id.startswith("__"):
        raise ValueError("Private names are not allowed")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in allowed_calls:
            raise ValueError("Only whitelisted function calls are allowed")

scope = dict(payload["inputs"])
exec(compile(tree, "<scenario-script>", "exec"), {"__builtins__": allowed_calls}, scope)
print(json.dumps({name: scope.get(name) for name in payload["outputs"]}, ensure_ascii=False))
'''


_JAVASCRIPT_RUNNER = r'''
const vm = require("node:vm");
let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => raw += chunk);
process.stdin.on("end", () => {
  const payload = JSON.parse(raw);
  const context = Object.assign(Object.create(null), payload.inputs);
  context.console = undefined;
  vm.createContext(context, {codeGeneration: {strings: false, wasm: false}});
  new vm.Script('"use strict";\n' + payload.code, {filename: "scenario-script.js"})
    .runInContext(context, {timeout: payload.timeout_ms});
  const result = Object.create(null);
  for (const name of payload.outputs) result[name] = context[name];
  process.stdout.write(JSON.stringify(result));
});
'''


def run_scenario_script(
    *,
    language: str,
    code: str,
    inputs: dict[str, Any],
    outputs: list[str],
    timeout_ms: int,
) -> dict[str, Any]:
    if len(code.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise ValueError("Script exceeds the 100 KB limit")
    payload = json.dumps(
        {
            "code": code,
            "inputs": inputs,
            "outputs": outputs,
            "timeout_ms": timeout_ms,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("Script inputs exceed the 1 MB limit")

    if language == "python":
        command = [sys.executable, "-I", "-S", "-c", _PYTHON_RUNNER]
    elif language == "javascript":
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("JavaScript runtime is unavailable")
        command = [node, "--max-old-space-size=64", "-e", _JAVASCRIPT_RUNNER]
    else:
        raise ValueError("Unsupported script language")

    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR"}
    }
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="scenario-script-") as working_dir:
        try:
            completed = subprocess.run(
                command,
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=working_dir,
                env=environment,
                timeout=timeout_ms / 1000,
                check=False,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Script execution timed out") from exc
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message[-2000:] or "Script execution failed")
    if len(completed.stdout) > MAX_OUTPUT_BYTES:
        raise ValueError("Script outputs exceed the 1 MB limit")
    result = json.loads(completed.stdout.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Script output must be an object")
    return result
