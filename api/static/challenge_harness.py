"""Grades learner code against a challenge's tests.

This one file runs in two places: in the learner's browser (Pyodide, so the server
never executes anyone's code) and in CPython for our own unit tests, which prove
every reference solution passes and every starter fails.
"""
import contextlib
import io
import re

MAX_MESSAGE = 300
MAX_STDOUT = 2000


def _short(exc):
    text = "{}: {}".format(type(exc).__name__, exc)
    return re.sub(r"\s+", " ", text)[:MAX_MESSAGE]


def run_challenge(user_code, tests_src):
    """Return {ok, passed, error, results:[{name, passed, message}], stdout}."""
    out = io.StringIO()
    namespace = {"__name__": "learner_solution"}
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(user_code, "<your code>", "exec"), namespace)
    except BaseException as exc:  # includes SyntaxError and SystemExit from sys.exit()
        return {"ok": False, "passed": False, "error": _short(exc), "results": [], "stdout": out.getvalue()[:MAX_STDOUT]}

    test_namespace = {"__name__": "challenge_tests"}
    exec(compile(tests_src, "<tests>", "exec"), test_namespace)

    results = []
    for name, fn in list(test_namespace.items()):
        if not (name.startswith("test_") and callable(fn)):
            continue
        label = (fn.__doc__ or name).strip().splitlines()[0]
        try:
            with contextlib.redirect_stdout(out):
                fn(namespace)
            results.append({"name": label, "passed": True, "message": ""})
        except AssertionError as exc:
            results.append({"name": label, "passed": False, "message": str(exc)[:MAX_MESSAGE] or "The result was not what was expected."})
        except BaseException as exc:
            results.append({"name": label, "passed": False, "message": _short(exc)})
    return {
        "ok": True,
        "passed": bool(results) and all(r["passed"] for r in results),
        "error": None,
        "results": results,
        "stdout": out.getvalue()[:MAX_STDOUT],
    }
