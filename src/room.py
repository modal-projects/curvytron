"""The sessioned Curvytron room server."""

import os
import subprocess

import modal

from .common import app, room_image
from .config import (
    APP_NAME,
    ASHBURN_METRO,
    BUFFER_CONTAINERS,
    CURVYTRON_DIR,
    DOMAIN_ENV,
    LOBBY_DOMAIN,
    MAX_CONTAINERS,
    PORT,
    REGION,
    ROOM_CPU,
    ROOM_SCALEDOWN_WINDOW,
    ROOMS_PER_CONTAINER,
    SESSION_QUEUE_TIMEOUT,
    TARGET_ROOMS_PER_CONTAINER,
)


def lobby_url() -> str:
    """Resolve the lobby's public URL for this app, including under `modal serve`."""
    if LOBBY_DOMAIN:
        return f"https://{LOBBY_DOMAIN}"
    try:
        from modal.app import _App

        container_app = _App._get_container_app()
        running = container_app._running_app if container_app is not None else None
        if running is not None and hasattr(modal.Function, "from_id"):
            function = modal.Function.from_id(running.function_ids["lobby"])
        else:
            function = modal.Function.from_name(APP_NAME, "lobby")
        return (function.get_web_url() or "").rstrip("/")
    except Exception as error:  # noqa: BLE001
        print(f"lobby url unavailable: {error}")
        return ""


@app.server(
    image=room_image,
    port=PORT,
    cpu=ROOM_CPU,
    env=DOMAIN_ENV,
    target_concurrency=TARGET_ROOMS_PER_CONTAINER,
    max_concurrency=ROOMS_PER_CONTAINER,
    max_containers=MAX_CONTAINERS,
    min_containers=1,
    buffer_containers=BUFFER_CONTAINERS,
    routing_region=REGION,
    compute_region=ASHBURN_METRO,
    nonpreemptible=True,
    startup_timeout=60,
    scaledown_window=ROOM_SCALEDOWN_WINDOW,
    experimental_options={"queue_timeout": SESSION_QUEUE_TIMEOUT},
)
@modal.sessioned()
class Room:
    @modal.enter()
    def start(self) -> None:
        self.process = subprocess.Popen(
            ["npm", "start"],
            cwd=CURVYTRON_DIR,
            env={**os.environ, "LOBBY_URL": lobby_url()},
        )

    @modal.exit()
    def stop(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)
