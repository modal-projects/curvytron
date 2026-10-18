"""Curvytron multiplayer game demo, hosted on Modal with Sticky Sessions.

Runs Curvytron (https://github.com/Curvytron/curvytron, MIT), a browser clone of
Achtung, die Kurve! using Modal Sticky Sessions.

The `ui` launcher starts a session per room and shows an invite link of the form
`<server>/?modal_session_token=<token>#/room/<name>`. Modal exchanges the query
parameter for a session cookie, which the page and its WebSocket then send. Once a
room has been empty for `ROOM_IDLE_TIMEOUT`, its session ends and the link stops
working.

Check routing with `modal run -m src.app`.
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
ROOMS_PER_CONTAINER = 8
MAX_CONTAINERS = 2
REGION = "us-east"
ROOM_IDLE_TIMEOUT = 5 * MINUTES


@app.server(
    image=image,
    port=PORT,
    max_concurrency=ROOMS_PER_CONTAINER,
    max_containers=MAX_CONTAINERS,
    routing_region=REGION,
    compute_region=REGION,
    startup_timeout=1 * MINUTES,
)
@modal.sessioned()
class Curvytron:
    @modal.enter()
    def start(self):
        import subprocess

        self.process = subprocess.Popen(["npm", "start"], cwd=CURVYTRON_DIR)


launcher_image = modal.Image.debian_slim(python_version="3.12").uv_pip_install("fastapi[standard]==0.116.1")


@app.function(image=launcher_image)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def ui():
    import html
    import secrets

    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    web_app = FastAPI()

    @web_app.get("/")
    async def index():
        return HTMLResponse(PAGE_HTML.format(body=CREATE_ROOM_HTML))

    @web_app.post("/new")
    async def new_room():
        session = await Curvytron.sessions.start.aio(idle_timeout=ROOM_IDLE_TIMEOUT)
        server_url = await Curvytron.get_url.aio()
        # Rooms on a container share one Curvytron process, so names must not collide.
        room = f"room-{secrets.token_hex(3)}"
        invite = f"{server_url}/?modal_session_token={session.token}#/room/{room}"
        body = INVITE_HTML.format(invite=html.escape(invite))
        return HTMLResponse(PAGE_HTML.format(body=body))

    return web_app


PAGE_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Curvytron on Modal</title>
  </head>
  <body style="font-family: sans-serif; max-width: 32rem; margin: 4rem auto; padding: 0 1rem;">
    <h1>Curvytron on Modal</h1>
    {body}
  </body>
</html>
"""

CREATE_ROOM_HTML = """
    <p>Create a room and share its invite link with your friends.</p>
    <form method="post" action="new">
      <button type="submit">Create a room</button>
    </form>
"""

INVITE_HTML = """
    <p>Your room is ready. Send this invite link to your friends,
       then join using the same link.</p>
    <p><input id="invite" value="{invite}" readonly style="width: 100%; box-sizing: border-box;"></p>
    <p>
      <button id="copy" type="button">Copy invite link</button>
      <a href="{invite}">Play</a>
    </p>
    <script>
      const copy = document.getElementById("copy");
      copy.addEventListener("click", async () => {{
        await navigator.clipboard.writeText(document.getElementById("invite").value);
        copy.textContent = "Copied!";
      }});
    </script>
"""


@app.local_entrypoint()
def test():
    """Create a room, load it with the invite link's token, and check that tokenless requests are refused."""
    import html
    import re
    import urllib.error
    import urllib.request
    from urllib.parse import parse_qs, urlparse

    with urllib.request.urlopen(urllib.request.Request(f"{ui.get_web_url()}/new", data=b"")) as resp:
        page = resp.read().decode()
    invite = urlparse(html.unescape(re.search(r'href="([^"]+)"', page).group(1)))
    token = parse_qs(invite.query)["modal_session_token"][0]
    server_url = f"{invite.scheme}://{invite.netloc}"
    print(f"Created room {invite.fragment.removeprefix('/room/')!r}")

    request = urllib.request.Request(server_url, headers={"Modal-Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request) as resp:
        assert "Curvytron" in resp.read().decode()
    print("Curvytron served the room's session")

    try:
        urllib.request.urlopen(server_url)
        raise AssertionError("Server accepted a request without a session token")
    except urllib.error.HTTPError as exc:
        assert exc.code == 401, f"expected 401 without a session token, got {exc.code}"
    print("Curvytron rejected a request without a session token")
