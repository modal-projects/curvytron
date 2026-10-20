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
every player in a room reaches the same container. A session ends once its room has
been empty for `ROOM_IDLE_TIMEOUT`.

`<launcher>/` opens Curvytron's lobby on one shared lobby session, stored in the same
Dict, and the lobby creates rooms through `<launcher>/room/<name>`. Each container
reports its rooms to a second Dict, and the lobby lists rooms from every container
through `<launcher>/rooms`.

Check routing with `modal run -m src.app`.
"""

import modal

app = modal.App("curvytron")

CURVYTRON_REPO = "https://github.com/KartikYZ/curvytron"
CURVYTRON_COMMIT = "48665a06392da75ed8a64e4667adf484004a47b9"
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
LOBBY_KEY = ("lobby",)
ROOM_REPORT_INTERVAL = 3
ROOM_REPORT_TTL = 15


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
        import threading

        env = {**os.environ, "CURVYTRON_LAUNCHER_URL": ui.get_web_url()}
        self.process = subprocess.Popen(["npm", "start"], cwd=CURVYTRON_DIR, env=env)
        threading.Thread(target=self.report_rooms, daemon=True).start()

    def report_rooms(self):
        import json
        import os
        import time
        import urllib.request

        while True:
            time.sleep(ROOM_REPORT_INTERVAL)
            try:
                with urllib.request.urlopen(f"http://localhost:{PORT}/rooms", timeout=2) as resp:
                    listed = json.load(resp)
                room_reports.put(os.environ["MODAL_TASK_ID"], {"rooms": listed, "updated": time.time()})
            except Exception as exc:
                print(f"Could not report rooms: {exc}")

    @modal.exit()
    def stop(self):
        import os

        room_reports.pop(os.environ["MODAL_TASK_ID"], None)


launcher_image = modal.Image.debian_slim(python_version="3.12").uv_pip_install("fastapi[standard]==0.116.1")

rooms = modal.Dict.from_name("curvytron-rooms", create_if_missing=True)
room_reports = modal.Dict.from_name("curvytron-room-reports", create_if_missing=True)


@app.function(image=launcher_image)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def ui():
    import secrets
    import time
    from collections.abc import Awaitable, Callable
    from urllib.parse import quote

    import httpx
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse, RedirectResponse

    web_app = FastAPI()

    async def request(method: str, url: str, token: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, headers={"Modal-Authorization": f"Bearer {token}"})
        if resp.status_code in (401, 404, 502):
            return False
        resp.raise_for_status()
        return True

    async def session_for(key, ready: Callable[[str], Awaitable[bool]]) -> str | None:
        token = await rooms.get.aio(key)
        if token is not None and await ready(token):
            return token
        if token is not None:
            await rooms.pop.aio(key, None)
        session = await Curvytron.sessions.start.aio(idle_timeout=ROOM_IDLE_TIMEOUT)
        if not await rooms.put.aio(key, session.token, skip_if_exists=True):
            await Curvytron.sessions.terminate.aio(session.token)
            return await session_for(key, ready)
        if await ready(session.token):
            return session.token
        return None

    @web_app.get("/")
    async def lobby():
        server_url = await Curvytron.get_url.aio()
        token = await session_for(LOBBY_KEY, lambda token: request("GET", f"{server_url}/modal.js", token))
        if token is None:
            raise HTTPException(status_code=503, detail="Could not open the lobby")
        return RedirectResponse(f"{server_url}/?modal_session_token={token}#/", status_code=303)

    @web_app.get("/rooms")
    async def list_rooms():
        listed = {}
        async for task_id, report in room_reports.items.aio():
            if time.time() - report["updated"] > ROOM_REPORT_TTL:
                await room_reports.pop.aio(task_id, None)
                continue
            for room in report["rooms"]:
                listed.setdefault(room["name"], room)
        headers = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}
        return JSONResponse(list(listed.values()), headers=headers)

    @web_app.get("/room/{room:path}")
    async def join_room(room: str, password: str | None = None):
        room = room[:ROOM_NAME_MAX_LENGTH].strip() or f"room-{secrets.token_hex(3)}"
        server_url = await Curvytron.get_url.aio()
        room_url = f"{server_url}/rooms/{quote(room, safe='')}"
        token = await session_for(room, lambda token: request("PUT", room_url, token))
        if token is None:
            raise HTTPException(status_code=503, detail="Could not open this room")
        fragment = f"/room/{quote(room, safe=URI_COMPONENT_SAFE)}"
        if password:
            fragment += f"?password={quote(password, safe='')}"
        return RedirectResponse(f"{server_url}/?modal_session_token={token}#{fragment}", status_code=303)

    return web_app


@app.local_entrypoint()
def test():
    """Open the lobby and rooms through the launcher, and check joins share a session that rooms outlive."""
    import json
    import secrets
    import time
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

    lobby = urlparse(redirect_location(ui.get_web_url()))
    assert lobby.fragment == "/", lobby.fragment
    assert redirect_location(ui.get_web_url()) == lobby.geturl(), "a second lobby visit got a different session"
    print("Both lobby visits got the same session")

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

    for _ in range(10):
        with urllib.request.urlopen(f"{ui.get_web_url()}/rooms") as resp:
            listed = {r["name"] for r in json.load(resp)}
        if room in listed and spaced_room in listed:
            break
        time.sleep(2)
    assert room in listed and spaced_room in listed, listed
    print("The launcher listed both rooms")

    Curvytron.sessions.terminate(token)
    _, new_token = join(room)
    assert new_token != token, "joining after the session ended reused its token"
    print("Joining after the session ended started a new session")

    blank = urlparse(redirect_location(f"{ui.get_web_url()}/room/%20%20"))
    assert blank.fragment.startswith("/room/room-"), blank.fragment
    print(f"A blank room name opened {blank.fragment.removeprefix('/room/')!r}")
