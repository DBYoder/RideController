"""Minimal async test support, so the dev dependencies stay at just pytest."""

from __future__ import annotations

import asyncio
import inspect

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: run this coroutine test function with asyncio.run"
    )


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    test = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test):
        return None
    kwargs = {
        name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(test(**kwargs))
    return True
