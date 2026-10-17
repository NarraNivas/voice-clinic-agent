"""Run a FastAPI app on a real localhost port in a background thread.

Used by the recovery journey and its tests, so the two services talk over actual HTTP rather than
through an in-process test client. Ports are chosen by the operating system, so nothing collides
with a server you already have running.
"""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import uvicorn
from fastapi import FastAPI


@dataclass(frozen=True)
class RunningServer:
    base_url: str
    port: int


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def serve(app: FastAPI, *, timeout: float = 10.0) -> Iterator[RunningServer]:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError(f"server on port {port} did not start")
        time.sleep(0.02)
    try:
        yield RunningServer(base_url=f"http://127.0.0.1:{port}", port=port)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
