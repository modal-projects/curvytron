"""The Curvytron lobby, which routes named rooms to sessioned Room servers."""

import asyncio
import json
import secrets
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import modal

from .common import app, lobby_image, rooms
from .config import (
    APP_NAME,
    CURVYTRON_DIR,
    DOMAIN_ENV,
    LOBBY_DOMAIN,
    LOBBY_SCALEDOWN_WINDOW,
    ROOM_IDLE_TIMEOUT,
    ROOM_NAME_MAX_LENGTH,
    ROOMS_CACHE_TTL,
    WARMUP_INTERVAL,
    WARMUP_SESSION_IDLE_TIMEOUT,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

URI_COMPONENT_SAFE = "!'()*~"
ADJECTIVES = [
    "awesome",
    "amazing",
    "great",
    "fantastic",
    "super",
    "admirable",
    "famous",
    "fine",
    "gigantic",
    "grand",
    "marvelous",
    "mighty",
    "outstanding",
    "splendid",
    "wonderful",
    "big",
    "super",
    "smashing",
    "sensational",
]
NOUNS = [
    "game",
    "adventure",
    "fun zone",
    "arena",
    "party",
    "tournament",
    "league",
    "gala",
    "gathering",
    "bunch",
    "fight",
    "battle",
    "conflict",
    "encounter",
    "clash",
    "combat",
    "confrontation",
    "challenge",
]


def room_server() -> modal.Server:
    """Handle the Room server without importing its decorator into the lobby container."""
    from modal.app import _App

    container_app = _App._get_container_app()
    running = container_app._running_app if container_app is not None else None
    if running is not None and hasattr(modal.Server, "from_id"):
        return modal.Server.from_id(running.function_ids["Room"])
    return modal.Server.from_name(APP_NAME, "Room")


async def warm_room() -> None:
    """Start a short-lived session so a Room container is ready for the first player."""
    try:
        await room_server().sessions.start.aio(idle_timeout=WARMUP_SESSION_IDLE_TIMEOUT)
    except Exception as error:  # noqa: BLE001
        print(f"room warm-up failed: {error}")


def build_api(
    warm: Callable[[], Coroutine[Any, Any, None]] = warm_room,
    static_dir: str | Path = f"{CURVYTRON_DIR}/web",
) -> "FastAPI":
    from urllib.parse import quote, urlencode

    import httpx
    from fastapi import FastAPI, HTTPException, Response
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    api = FastAPI()
    rooms_cache: list[dict[str, Any]] | None = None
    rooms_cache_at = 0.0
    rooms_cache_lock = asyncio.Lock()
    last_warmup = 0.0

    async def open_room(server_url: str, token: str, name: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.put(
                    f"{server_url}/rooms/{quote(name, safe='')}",
                    headers={"Modal-Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError:
            return False

        if response.status_code in (200, 201):
            return True
        if response.status_code in (401, 404, 502):
            return False
        response.raise_for_status()
        return False

    async def session_for(name: str, server_url: str) -> dict[str, str] | None:
        server = room_server()
        for _ in range(3):
            entry = await rooms.get.aio(name)
            if entry is not None:
                token = entry["token"]
                if await open_room(server_url, token, name):
                    return entry
                await rooms.pop.aio(name, None)

            session = await server.sessions.start.aio(idle_timeout=ROOM_IDLE_TIMEOUT)
            new_entry = {"session_id": session.session_id, "token": session.token}
            if not await rooms.put.aio(name, new_entry, skip_if_exists=True):
                await server.sessions.terminate.aio(session.token)
                winner = await rooms.get.aio(name)
                if winner is not None:
                    token = winner["token"]
                    if await open_room(server_url, token, name):
                        return winner
                    await rooms.pop.aio(name, None)
                continue

            if await open_room(server_url, session.token, name):
                return new_entry
            await rooms.pop.aio(name, None)
            return None
        return None

    async def list_rooms() -> list[dict[str, Any]]:
        nonlocal rooms_cache, rooms_cache_at
        now = time.monotonic()
        if rooms_cache is not None and now - rooms_cache_at < ROOMS_CACHE_TTL:
            return rooms_cache

        async with rooms_cache_lock:
            now = time.monotonic()
            if rooms_cache is not None and now - rooms_cache_at < ROOMS_CACHE_TTL:
                return rooms_cache

            server_url = cast(str, await room_server().get_url.aio()).rstrip("/")
            entries = [entry async for entry in rooms.items.aio()]
            async with httpx.AsyncClient(timeout=10) as client:

                async def get_room(name: str, entry: Any) -> dict[str, Any] | None:
                    token = entry["token"]
                    try:
                        response = await client.get(
                            f"{server_url}/rooms/{quote(name, safe='')}",
                            headers={"Modal-Authorization": f"Bearer {token}"},
                        )
                    except httpx.HTTPError:
                        await rooms.pop.aio(name, None)
                        return None

                    if response.status_code == 404:
                        await rooms.pop.aio(name, None)
                        return None
                    if response.status_code != 200:
                        await rooms.pop.aio(name, None)
                        return None
                    try:
                        return response.json()
                    except ValueError:
                        await rooms.pop.aio(name, None)
                        return None

                results = await asyncio.gather(*(get_room(name, entry) for name, entry in entries))

            rooms_cache = [room for room in results if room is not None]
            rooms_cache_at = time.monotonic()
            return rooms_cache

    def invalidate_rooms_cache() -> None:
        nonlocal rooms_cache, rooms_cache_at
        rooms_cache = None
        rooms_cache_at = 0.0

    @api.get("/modal.js")
    async def modal_config() -> Response:
        url = f"https://{LOBBY_DOMAIN}" if LOBBY_DOMAIN else (await lobby.get_web_url.aio() or "").rstrip("/")
        config = json.dumps({"isLobby": True, "url": url})
        return Response(
            f"window.CURVYTRON_LOBBY = {config};",
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @api.get("/rooms")
    async def get_rooms() -> list[dict[str, Any]]:
        return await list_rooms()

    @api.get("/room/{name:path}")
    async def join_room(name: str, password: str | None = None) -> RedirectResponse:
        name = name[:ROOM_NAME_MAX_LENGTH].strip()
        if not name:
            while True:
                name = f"The {secrets.choice(ADJECTIVES)} {secrets.choice(NOUNS)}"
                if await rooms.get.aio(name) is None:
                    break

        server_url = cast(str, await room_server().get_url.aio()).rstrip("/")
        entry = await session_for(name, server_url)
        if entry is None:
            raise HTTPException(status_code=503, detail="Could not open this room")

        token = entry["token"]
        encoded_name = quote(quote(name, safe=URI_COMPONENT_SAFE), safe=URI_COMPONENT_SAFE)
        fragment = f"/room/{encoded_name}"
        if password is not None:
            fragment += f"?{urlencode({'password': password})}"
        location = f"{server_url}/?{urlencode({'modal_session_token': token})}#{fragment}"
        invalidate_rooms_cache()
        return RedirectResponse(location, status_code=302)

    @api.get("/")
    async def index() -> FileResponse:
        nonlocal last_warmup
        now = time.monotonic()
        if now - last_warmup >= WARMUP_INTERVAL:
            last_warmup = now
            asyncio.create_task(warm())
        return FileResponse(Path(static_dir) / "index.html")

    api.mount("/", StaticFiles(directory=str(static_dir)), name="static")
    return api


@app.function(
    image=lobby_image,
    max_containers=3,
    min_containers=1,
    scaledown_window=LOBBY_SCALEDOWN_WINDOW,
    env=DOMAIN_ENV,
)
@modal.concurrent(max_inputs=50, target_inputs=25)
@modal.asgi_app(custom_domains=[LOBBY_DOMAIN] if LOBBY_DOMAIN else None)
def lobby() -> "FastAPI":
    return build_api()
