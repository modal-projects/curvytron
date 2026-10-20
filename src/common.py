"""Shared Modal objects for the Curvytron lobby and room server."""

import modal

from .config import APP_NAME, CURVYTRON_COMMIT, CURVYTRON_DIR, CURVYTRON_PATCH, CURVYTRON_REPO

app = modal.App(APP_NAME)

room_image = (
    modal.Image.from_registry("node:22-bookworm-slim", add_python="3.12")
    .apt_install("git")
    .run_commands(
        f"git clone {CURVYTRON_REPO} {CURVYTRON_DIR}",
        f"cd {CURVYTRON_DIR} && git checkout {CURVYTRON_COMMIT}",
    )
    .add_local_file(CURVYTRON_PATCH, f"{CURVYTRON_DIR}/curvytron.patch", copy=True)
    .run_commands(
        f"cd {CURVYTRON_DIR} && git apply curvytron.patch",
        f"cd {CURVYTRON_DIR} && cp config.json.sample config.json && npm ci && npm run build",
    )
)

lobby_image = room_image.uv_pip_install("fastapi[standard]==0.116.1")

rooms = modal.Dict.from_name(f"{APP_NAME}-rooms", create_if_missing=True)
