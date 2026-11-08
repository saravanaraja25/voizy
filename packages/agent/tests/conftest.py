from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi import FastAPI
from voizy_agent.devtools.mock_clinic import DEV_API_KEY, create_mock_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve(app: FastAPI) -> Iterator[int]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "mock clinic did not start"
    yield port
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def clinic_port() -> Iterator[int]:
    """An open mock clinic on loopback, so the executor's sockets are genuinely exercised."""
    yield from _serve(create_mock_app(0))


@pytest.fixture(scope="module")
def secure_clinic_app() -> FastAPI:
    return create_mock_app(0, api_key=DEV_API_KEY)


@pytest.fixture(scope="module")
def secure_clinic_port(secure_clinic_app: FastAPI) -> Iterator[int]:
    """The same backend, but every data endpoint demands the key."""
    yield from _serve(secure_clinic_app)
