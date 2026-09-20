"""Built-in tutor used when the AI service is unavailable.

Everything here is deterministic: lesson goals and starters, the automated checks,
a structural read of the code, and curated pointers to official documentation.
It never pretends to be the AI; it labels itself and stays useful.
"""
from __future__ import annotations

import ast
import re

BANNER = (
    "**Offline mode.** Aria's AI service isn't reachable right now, so this is built-in guidance "
    "(no AI). The automated checks still ran. Try again in a minute for a full explanation."
)

DOCS = {
    "python": ["Python tutorial: https://docs.python.org/3/tutorial/", "Real Python guides: https://realpython.com/"],
    "java": ["Oracle Java tutorials: https://docs.oracle.com/javase/tutorial/", "Baeldung: https://www.baeldung.com/"],
    "spring": ["Spring guides: https://spring.io/guides", "Spring Boot reference: https://docs.spring.io/spring-boot/reference/"],
    "datascience": [
        "pandas user guide: https://pandas.pydata.org/docs/user_guide/",
        "scikit-learn user guide: https://scikit-learn.org/stable/user_guide.html",
        "Statistics refresher: https://www.khanacademy.org/math/statistics-probability",
    ],
}

CHECKLISTS = {
    "python": ["Does every function do one thing?", "Are errors handled or logged, never silenced?", "Have you run it with an empty, a normal and a bad input?"],
    "java": ["Are fields private with behaviour in methods?", "Are exceptions handled, never swallowed?", "Have you tested null, empty and boundary values?"],
    "spring": ["Are dependencies injected through the constructor?", "Is every request body validated?", "Is authentication required by default?", "Do you have a test for the happy path and one failure?"],
    "datascience": ["What decision will this answer change?", "Was any fitting done before the train/test split?", "Is there a simple baseline to compare with?", "What could make this result misleading?"],
}


def _findings_block(findings: list[dict]) -> str:
    if not findings:
        return "No automated issues found. That does not prove the code is correct, so run it and test edge cases."
    icon = {"error": "ERROR", "warning": "WARNING", "tip": "TIP"}
    return "\n".join(f"- {icon.get(f['severity'], f['severity'].upper())}: {f['message']}" for f in findings)


def _docs_block(language: str) -> str:
    return "\n".join(f"- {line}" for line in DOCS.get(language, []))


def _python_structure(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"The code doesn't parse yet: {exc.msg} on line {exc.lineno}."]
    out: list[str] = []
    imports = sorted({(n.module or "") if isinstance(n, ast.ImportFrom) else a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])} - {""})
    if imports:
        out.append("Uses libraries: " + ", ".join(imports) + ".")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ", ".join(a.arg for a in node.args.args)
            out.append(f"Function `{node.name}({args})` on line {node.lineno}.")
        elif isinstance(node, ast.ClassDef):
            out.append(f"Class `{node.name}` on line {node.lineno}.")
    loops = sum(isinstance(n, (ast.For, ast.While)) for n in ast.walk(tree))
    branches = sum(isinstance(n, ast.If) for n in ast.walk(tree))
    if loops or branches:
        out.append(f"Contains {loops} loop(s) and {branches} if-branch(es).")
    return out or ["Only top-level statements, with no functions or classes."]


def _java_structure(code: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"\b(class|interface|record|enum)\s+(\w+)", code):
        out.append(f"{m.group(1).capitalize()} `{m.group(2)}`.")
    annotations = sorted(set(re.findall(r"@(\w+)", code)) - {"Override"})
    if annotations:
        out.append("Annotations used: " + ", ".join("@" + a for a in annotations) + ".")
    for m in re.finditer(r"(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\], ?]+\s+(\w+)\s*\(([^)]*)\)", code):
        out.append(f"Method `{m.group(1)}({m.group(2).strip()})`.")
    return out or ["No classes or methods detected yet."]


def _structure(language: str, code: str) -> list[str]:
    return _java_structure(code) if language in {"java", "spring"} else _python_structure(code)


def _todos(starter: str) -> list[str]:
    return [re.sub(r"^\W*TODO:?\s*", "", line.strip()).strip() for line in starter.splitlines() if "TODO" in line]


def _context_columns(context: str) -> list[str]:
    return [line[2:] for line in context.splitlines() if line.startswith("- ") and ":" in line and "missing" in line]


def _context_issues(context: str) -> list[str]:
    _, _, tail = context.partition("Detected quality issues:")
    return [line[2:] for line in tail.splitlines() if line.startswith("- ") and line[2:] != "none"]


def offline_response(
    *, language: str, level: str, mode: str, code: str = "", lesson: dict | None = None,
    findings: list[dict] | None = None, context: str = "",
) -> str:
    findings = findings or []
    parts = [BANNER, ""]

    if mode == "teach" and lesson:
        parts += [f"## {lesson['title']}", f"**Goal:** {lesson['goal']}", "", "### Starter code", f"```{'python' if language in {'python', 'datascience'} else 'java'}", lesson["starter"].rstrip(), "```", ""]
        todos = _todos(lesson["starter"])
        if todos:
            parts += ["### Your turn"] + [f"- {t}" for t in todos] + [""]
        parts += ["### How to work through it", "- Read the starter code slowly and say out loud what each line does.", "- Change one thing at a time and re-run so you can see what caused what.", "- Compare with the automated checks below, then look up anything unfamiliar in the docs.", ""]
        starter_findings = findings
        parts += ["### What the automated checks notice in the starter", _findings_block(starter_findings), ""]
    elif mode == "analyse":
        cols = _context_columns(context)
        issues = _context_issues(context)
        parts += ["## Your dataset at a glance", context.split("\n\n")[0] if context else "No summary available.", ""]
        if cols:
            parts += ["### Columns"] + [f"- {c}" for c in cols[:40]] + [""]
        parts += ["### Data-quality issues found", "\n".join(f"- {i}" for i in issues) if issues else "- None detected.", "", "### A sensible plan", "1. Use **Clean & download** to fix formats, duplicates and placeholders, then review **Show what changed**.", "2. Look at each column's distribution and missing values before modelling.", "3. Write down the question and the decision it supports, then start with the simplest baseline.", "4. Split train and test data before any fitting, and report uncertainty, not just one number.", ""]
    elif mode == "review":
        parts += ["## Review", "### Automated checks", _findings_block(findings), ""]
    else:
        parts += ["## What your code contains", "\n".join(f"- {line}" for line in _structure(language, code)), "", "### Automated checks", _findings_block(findings), ""]

    checklist = CHECKLISTS.get(language, [])
    if checklist and mode != "analyse":
        parts += ["### Self-review checklist"] + [f"- {c}" for c in checklist] + [""]
    parts += ["### Where to read more", _docs_block(language), ""]
    if level == "beginner":
        parts += ["Tip: the best way to learn is to run the code, break it on purpose, and fix it."]
    parts += ["Automated checks can miss things. Run the code and check the official docs."]
    return "\n".join(parts)
