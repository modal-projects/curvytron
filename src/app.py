"""Curvytron multiplayer game demo, hosted on Modal with Sticky Sessions.

Runs Curvytron (https://github.com/Curvytron/curvytron, MIT), a browser clone of
Achtung, die Kurve! using Modal Sticky Sessions.

Rooms are shared as `<launcher>/room/<name>` links. The `ui` launcher keeps a
room-to-session mapping in a Modal Dict: it starts a session the first time a room is
joined, or after the room's session has ended, and redirects every player to
`<server>/?modal_session_token=<token>#/room/<name>`. Modal exchanges the query
parameter for a session cookie, which Curvytron's page and WebSocket then send, so
every player in a room reaches the same container. `<launcher>/` redirects to a new
room. A session ends once its room has been empty for `ROOM_IDLE_TIMEOUT`.

Check routing with `modal run -m src.app`.
"""

import modal

app = modal.App("curvytron")

CURVYTRON_REPO = "https://github.com/Curvytron/curvytron"
CURVYTRON_COMMIT = "0051e59b173c244dfe30e539a227b01dc8216186"
CURVYTRON_DIR = "/curvytron"

# Stock Curvytron sends a player who joins an unknown room back to the lobby. Creating
# the room on first join lets invite links go straight into a fresh room.
JOIN_CREATES_ROOM_PATCH = (
    "s/var room = this.repository.get(data.name);"
    "/var room = this.repository.get(data.name) || this.repository.create(data.name);/"
)

image = (
    modal.Image.from_registry("node:22-bookworm-slim", add_python="3.12")
    .apt_install("git")
    .run_commands(
        f"git clone {CURVYTRON_REPO} {CURVYTRON_DIR}",
        f"cd {CURVYTRON_DIR} && git checkout {CURVYTRON_COMMIT}",
        f"cd {CURVYTRON_DIR} && sed -i '{JOIN_CREATES_ROOM_PATCH}' src/server/controller/RoomsController.js",
        f"cd {CURVYTRON_DIR} && cp config.json.sample config.json",
        f"cd {CURVYTRON_DIR} && npm ci && npm run build",
    )
)

MINUTES = 60
PORT = 8020
ROOMS_PER_CONTAINER = 10
MAX_CONTAINERS = 2
REGION = "us-east"
ROOM_IDLE_TIMEOUT = 5 * MINUTES
ROOM_NAME_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"


@app.server(
    image=image,
    port=PORT,
    max_concurrency=ROOMS_PER_CONTAINER,
    max_containers=MAX_CONTAINERS,
    min_containers=1,
    buffer_containers=1,
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

rooms = modal.Dict.from_name("curvytron-rooms", create_if_missing=True)


@app.function(image=launcher_image)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def ui():
    import secrets

    import httpx
    from fastapi import FastAPI, HTTPException, Path
    from fastapi.responses import RedirectResponse

    web_app = FastAPI()

    async def is_live(server_url: str, token: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.head(server_url, headers={"Modal-Authorization": f"Bearer {token}"})
        return resp.status_code not in (401, 404)

    async def session_for(room: str, server_url: str) -> str:
        token = await rooms.get.aio(room)
        if token is not None and await is_live(server_url, token):
            return token
        if token is not None:
            await rooms.pop.aio(room, None)
        session = await Curvytron.sessions.start.aio(idle_timeout=ROOM_IDLE_TIMEOUT)
        if await rooms.put.aio(room, session.token, skip_if_exists=True):
            return session.token
        await Curvytron.sessions.terminate.aio(session.token)
        return await rooms.get.aio(room)

    @web_app.get("/")
    async def new_room():
        return RedirectResponse(f"room/room-{secrets.token_hex(3)}", status_code=303)

    @web_app.get("/room/{room}")
    async def join_room(room: str = Path(pattern=ROOM_NAME_PATTERN)):
        server_url = await Curvytron.get_url.aio()
        token = await session_for(room, server_url)
        if token is None:
            raise HTTPException(status_code=503, detail="Could not start a session for this room")
        return RedirectResponse(f"{server_url}/?modal_session_token={token}#/room/{room}", status_code=303)

    return web_app


@app.local_entrypoint()
def test():
    """Join a room twice, check both joins share a session, and check that a room outlives its ended session."""
    import secrets
    import urllib.error
    import urllib.request
    from urllib.parse import parse_qs, urlparse

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)

    def redirect_location(url: str) -> str:
        try:
            opener.open(url)
        except urllib.error.HTTPError as exc:
            assert exc.code == 303, f"expected a 303 from {url}, got {exc.code}"
            return exc.headers["Location"]
        raise AssertionError(f"{url} did not redirect")

    def join(room: str) -> tuple[str, str]:
        location = urlparse(redirect_location(f"{ui.get_web_url()}/room/{room}"))
        assert location.fragment == f"/room/{room}", location.fragment
        return f"{location.scheme}://{location.netloc}", parse_qs(location.query)["modal_session_token"][0]

    assert redirect_location(ui.get_web_url()).startswith("room/room-")
    print("The launcher redirected to a new room")

    room = f"test-{secrets.token_hex(3)}"
    server_url, token = join(room)
    assert join(room) == (server_url, token), "a second join got a different session"
    print(f"Both joins of room {room!r} got the same session")

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

    Curvytron.sessions.terminate(token)
    _, new_token = join(room)
    assert new_token != token, "joining after the session ended reused its token"
    print("Joining after the session ended started a new session")

    try:
        opener.open(f"{ui.get_web_url()}/room/not%20a%20room")
        raise AssertionError("Launcher accepted an invalid room name")
    except urllib.error.HTTPError as exc:
        assert exc.code == 422, f"expected 422 for an invalid room name, got {exc.code}"
    print("The launcher rejected an invalid room name")
