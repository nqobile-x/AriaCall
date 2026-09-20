from __future__ import annotations

import os


def run_python(code: str, timeout: int = 30) -> dict:
    """
    Execute Python code in an E2B sandbox.
    Returns {"stdout": str, "stderr": str, "error": str | None}.
    Falls back to a safe local exec if E2B_API_KEY is not set (dev only).
    """
    api_key = os.getenv("E2B_API_KEY")
    if api_key:
        return _run_e2b(code, api_key, timeout)
    return _run_local_safe(code, timeout)


def _run_e2b(code: str, api_key: str, timeout: int) -> dict:
    try:
        from e2b_code_interpreter import Sandbox  # type: ignore
        with Sandbox(api_key=api_key, timeout=timeout) as sb:
            execution = sb.run_code(code)
            stdout = "\n".join(str(r) for r in execution.results if r)
            stderr = "\n".join(execution.error.traceback) if execution.error else ""
            return {"stdout": stdout, "stderr": stderr, "error": execution.error.value if execution.error else None}
    except ImportError:
        return {"stdout": "", "stderr": "", "error": "e2b_code_interpreter package not installed. Run: pip install e2b-code-interpreter"}
    except Exception as exc:
        return {"stdout": "", "stderr": "", "error": str(exc)}


def _run_local_safe(code: str, timeout: int) -> dict:
    """Dev fallback — restricted exec with no network/file access."""
    import io
    import contextlib
    out = io.StringIO()
    err_msg = None
    allowed_builtins = {
        "print": print, "range": range, "len": len, "str": str, "int": int,
        "float": float, "list": list, "dict": dict, "tuple": tuple, "set": set,
        "bool": bool, "abs": abs, "min": min, "max": max, "sum": sum,
        "sorted": sorted, "enumerate": enumerate, "zip": zip, "map": map,
        "filter": filter, "round": round, "isinstance": isinstance, "type": type,
        "__builtins__": {},
    }
    try:
        with contextlib.redirect_stdout(out):
            exec(code, {"__builtins__": allowed_builtins})  # noqa: S102
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
    return {"stdout": out.getvalue(), "stderr": "", "error": err_msg}
