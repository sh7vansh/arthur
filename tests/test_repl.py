"""Tests for arthur.repl — Persistent REPL Engine & Output Budgeting."""

import pytest
from arthur.browser import Browser
from arthur.repl import (
    OutputBudgetFormatter,
    PythonReplSession,
    defang_telemetry_payload,
)


def test_defang_telemetry_payload():
    raw_md = "Look at this image: ![tracker](https://evil.com/beacon.png) and <img src='https://evil.com/x.jpg' />."
    defanged = defang_telemetry_payload(raw_md)
    assert "[IMAGE_BLOCKED: tracker | https://evil.com/beacon.png]" in defanged
    assert "[TAG_BLOCKED: img src='https://evil.com/x.jpg' /]" in defanged
    assert "https://evil.com/beacon.png" in defanged
    assert "<img" not in defanged


def test_repl_statement_and_expression_persistence():
    session = PythonReplSession()

    # Step 1: define variables and function
    res1 = session.execute("""
x = 40
def add(a, b):
    return a + b
""")
    assert res1 == "(executed successfully with no output)"

    # Step 2: call function and evaluate trailing expression
    res2 = session.execute("""
y = add(x, 2)
y
""")
    assert "[result]\n42" in res2

    # Step 3: check '_' variable
    res3 = session.execute("_")
    assert "[result]\n42" in res3


def test_repl_stdout_and_result_capture():
    session = PythonReplSession()
    res = session.execute("""
print("Hello from Arthur!")
{"status": "ok", "items": [1, 2, 3]}
""")
    assert "[stdout]\nHello from Arthur!" in res
    assert "[result]\n" in res
    assert "'status': 'ok'" in res or '"status": "ok"' in res


def test_repl_syntax_error():
    session = PythonReplSession()
    res = session.execute("def invalid syntax")
    assert "[error]" in res
    assert "SyntaxError" in res


def test_repl_runtime_exception_with_auto_snapshot():
    fake_browser = Browser()
    session = PythonReplSession(browser_instance=fake_browser)

    html = "<html><head><title>Repl Test</title></head><body><button id='b1'>Click Me</button></body></html>"
    import urllib.parse
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    # Navigate
    session.execute(f"browser.navigate('{data_url}')")

    # Intentionally trigger an error (e.g. click nonexistent element)
    res = session.execute("browser.click(999)")
    assert "[error]" in res
    assert "ElementNotFoundError" in res
    assert "[diagnostic_auto_snapshot]" in res
    assert 'PAGE: "Repl Test"' in res

    fake_browser.close()


def test_repl_output_budget_truncation():
    formatter = OutputBudgetFormatter(max_chars=200)
    huge_str = "A" * 5000
    formatted = formatter.format_execution_result(result=huge_str, has_result=True)
    assert len(formatted) <= 300
    assert "chars / " in formatted or "tokens omitted" in formatted
