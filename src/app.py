"""Curvytron multiplayer game demo, hosted on Modal with Sticky Sessions.

Runs a fork of Curvytron (https://github.com/Curvytron/curvytron, MIT), a browser
clone of Achtung, die Kurve!, whose lobby creates rooms through a Sticky Sessions
launcher (https://github.com/KartikYZ/curvytron).

Rooms are shared as `<launcher>/room/<name>` links. The `ui` launcher keeps a
room-to-session mapping in a Modal Dict: it starts a session the first time a room is
joined, or after the room's session has ended, opens the room on that session's
container, and redirects every player to
`<server>/?modal_session_token=<token>#/room/<name>`. Modal exchanges the query
parameter for a session cookie, which Curvytron's page and WebSocket then send, so
every player in a room reaches the same container. `<launcher>/` redirects to a new
room. A session ends once its room has been empty for `ROOM_IDLE_TIMEOUT`.

Check routing with `modal run -m src.app`.
"""

import modal

app = modal.App("curvytron")

CURVYTRON_REPO = "https://github.com/KartikYZ/curvytron"
CURVYTRON_COMMIT = "4382557224a7b70150e8f1fd80a69611201933cf"
CURVYTRON_DIR = "/curvytron"

image = (
    modal.Image.from_registry("node:22-bookworm-slim", add_python="3.12")
    .apt_install("git")
    .run_commands(
        f"git clone {CURVYTRON_REPO} {CURVYTRON_DIR}",
        f"cd {CURVYTRON_DIR} && git checkout {CURVYTRON_COMMIT}",
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
ROOM_NAME_MAX_LENGTH = 25
URI_COMPONENT_SAFE = "!'()*~"


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
        import os
        import subprocess

        env = {**os.environ, "CURVYTRON_LAUNCHER_URL": ui.get_web_url()}
        self.process = subprocess.Popen(["npm", "start"], cwd=CURVYTRON_DIR, env=env)


launcher_image = modal.Image.debian_slim(python_version="3.12").uv_pip_install("fastapi[standard]==0.116.1")

rooms = modal.Dict.from_name("curvytron-rooms", create_if_missing=True)


@app.function(image=launcher_image)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def ui():
    import secrets
    from urllib.parse import quote

    import httpx
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import RedirectResponse

    web_app = FastAPI()

    async def open_room(server_url: str, token: str, room: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{server_url}/rooms/{quote(room, safe='')}",
                headers={"Modal-Authorization": f"Bearer {token}"},
            )
        if resp.status_code in (401, 404, 502):
            return False
        resp.raise_for_status()
        return True

    async def session_for(room: str, server_url: str) -> str | None:
        token = await rooms.get.aio(room)
        if token is not None and await open_room(server_url, token, room):
            return token
        if token is not None:
            await rooms.pop.aio(room, None)
        session = await Curvytron.sessions.start.aio(idle_timeout=ROOM_IDLE_TIMEOUT)
        if not await rooms.put.aio(room, session.token, skip_if_exists=True):
            await Curvytron.sessions.terminate.aio(session.token)
            return await session_for(room, server_url)
        if await open_room(server_url, session.token, room):
            return session.token
        return None

    @web_app.get("/")
    async def new_room():
        return RedirectResponse(f"room/room-{secrets.token_hex(3)}", status_code=303)

    @web_app.get("/room/{room:path}")
    async def join_room(room: str):
        room = room[:ROOM_NAME_MAX_LENGTH].strip()
        if not room:
            raise HTTPException(status_code=422, detail="Room name must not be blank")
        server_url = await Curvytron.get_url.aio()
        token = await session_for(room, server_url)
        if token is None:
            raise HTTPException(status_code=503, detail="Could not open this room")
        fragment = f"/room/{quote(room, safe=URI_COMPONENT_SAFE)}"
        return RedirectResponse(f"{server_url}/?modal_session_token={token}#{fragment}", status_code=303)

    return web_app


@app.local_entrypoint()
def test():
    """Join rooms through the launcher, check joins share a session, and check rooms outlive ended sessions."""
    import secrets
    import urllib.error
    import urllib.request
    from urllib.parse import parse_qs, quote, urlparse

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
        location = urlparse(redirect_location(f"{ui.get_web_url()}/room/{quote(room, safe='')}"))
        assert location.fragment == f"/room/{quote(room, safe=URI_COMPONENT_SAFE)}", location.fragment
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

    request = urllib.request.Request(f"{server_url}/modal.js", headers={"Modal-Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request) as resp:
        assert ui.get_web_url() in resp.read().decode()
    print("Curvytron's client config points at the launcher")

    spaced_room = f"Fun room {secrets.token_hex(2)}!"
    assert join(spaced_room) == join(spaced_room), "a room name with spaces got two sessions"
    print(f"Room {spaced_room!r} got one session")

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
        opener.open(f"{ui.get_web_url()}/room/%20%20")
        raise AssertionError("Launcher accepted a blank room name")
    except urllib.error.HTTPError as exc:
        assert exc.code == 422, f"expected 422 for a blank room name, got {exc.code}"
    print("The launcher rejected a blank room name")
