"""Validate the inline JavaScript in static/customer.html.

A single stray newline inside a quoted string once shipped a SyntaxError that
only appeared in the browser. This test extracts the <script> block and checks
its syntax so it can never ship again. Uses `node --check` when Node is
available; otherwise a string/comment/template-literal-aware Python checker.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parent.parent / "static" / "customer.html"


def _extract_script(html: str) -> str:
    start = html.index("<script>") + len("<script>")
    end = html.index("</script>", start)
    return html[start:end]


def _check_with_python(js: str):
    """Catch unterminated strings and unbalanced (){}[] outside strings/comments.

    Templates are skipped wholesale (our templates don't nest backticks), and the
    remaining real code is checked for balanced brackets. A newline inside a
    single/double quoted string is the exact regression we guard against.
    """
    cleaned = []
    i, n = 0, len(js)
    while i < n:
        c = js[i]
        nxt = js[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            i += 2
            while i < n and js[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (js[i] == "*" and js[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if c in ("'", '"'):
            quote = c
            i += 1
            while i < n:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == quote:
                    i += 1
                    break
                if js[i] == "\n":
                    raise AssertionError("Unterminated string literal (newline inside quotes)")
                i += 1
            else:
                raise AssertionError("Unterminated string literal at end of script")
            cleaned.append(" ")
            continue
        if c == "`":
            i += 1
            while i < n:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == "`":
                    i += 1
                    break
                i += 1
            else:
                raise AssertionError("Unterminated template literal at end of script")
            cleaned.append(" ")
            continue
        cleaned.append(c)
        i += 1

    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for c in cleaned:
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != pairs[c]:
                raise AssertionError(f"Unbalanced brackets near {c!r}")
            stack.pop()
    if stack:
        raise AssertionError(f"Unbalanced brackets remaining: {stack}")


def test_customer_html_js_is_valid():
    js = _extract_script(HTML.read_text(encoding="utf-8"))

    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js)
            path = f.name
        r = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, f"node --check failed:\n{r.stderr}"
    else:
        # Python fallback: must not raise.
        _check_with_python(js)


def test_no_raw_newline_inside_single_quoted_string():
    """Regression guard for the exact bug: a single-quoted string split across lines."""
    js = _extract_script(HTML.read_text(encoding="utf-8"))
    # The Python checker raises on this; assert it passes.
    _check_with_python(js)