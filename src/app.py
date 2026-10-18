"""Curvytron multiplayer game demo, hosted on Modal.

Runs Curvytron (https://github.com/Curvytron/curvytron, MIT), a browser clone of
Achtung, die Kurve!, on a single always-on container. Curvytron keeps rooms in process
memory, so one container lets everyone play together at the server's URL.

Check that it serves with `modal run -m src.app`.
"""

from pathlib import Path

import modal

app = modal.App("curvytron")

CURVYTRON_REPO = "https://github.com/Curvytron/curvytron"
CURVYTRON_COMMIT = "0051e59b173c244dfe30e539a227b01dc8216186"
CURVYTRON_DIR = "/curvytron"

# Patches on top of the pinned commit, applied in order (see `patches/README.md`).
PATCHES_DIR = Path(__file__).parent.parent / "patches"

image = (
    modal.Image.from_registry("node:22-bookworm-slim", add_python="3.12")
    .apt_install("git")
    .add_local_dir(PATCHES_DIR, "/patches", copy=True)
    .run_commands(
        f"git clone {CURVYTRON_REPO} {CURVYTRON_DIR}",
        f"cd {CURVYTRON_DIR} && git checkout {CURVYTRON_COMMIT}",
        f"cd {CURVYTRON_DIR} && git apply /patches/*.patch",
        f"cd {CURVYTRON_DIR} && cp config.json.sample config.json",
        f"cd {CURVYTRON_DIR} && npm ci && npm run build",
    )
)

MINUTES = 60
PORT = 8020
REGION = "us-east"


@app.server(
    image=image,
    port=PORT,
    min_containers=1,
    max_containers=1,
    unauthenticated=True,
    routing_region=REGION,
    compute_region=REGION,
    startup_timeout=1 * MINUTES,
)
class Curvytron:
    @modal.enter()
    def start(self):
        import subprocess

        self.process = subprocess.Popen(["npm", "start"], cwd=CURVYTRON_DIR)


@app.local_entrypoint()
def test():
    """Load the game page from the server's URL."""
    import urllib.request

    url = Curvytron.get_url()
    with urllib.request.urlopen(url) as resp:
        assert "Curvytron" in resp.read().decode()
    print(f"Curvytron is serving at {url}")
