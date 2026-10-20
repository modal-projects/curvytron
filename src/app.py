"""Curvytron on Modal, with a web-function lobby and sessioned room servers."""

from . import lobby, room  # noqa: F401
from .common import app


@app.local_entrypoint()
def test() -> None:
    """Check lobby redirects, shared sessions, and session replacement."""
    import json
    import secrets
    import urllib.error
    import urllib.request
    from urllib.parse import parse_qs, quote, urlparse

    from .lobby import URI_COMPONENT_SAFE, lobby as lobby_function

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    lobby_url = lobby_function.get_web_url().rstrip("/")

    def redirect_location(url: str) -> str:
        try:
            opener.open(url)
        except urllib.error.HTTPError as error:
            assert error.code == 302, f"expected a 302 from {url}, got {error.code}"
            return error.headers["Location"]
        raise AssertionError(f"{url} did not redirect")

    def join(name: str) -> tuple[str, str, str]:
        location = urlparse(redirect_location(f"{lobby_url}/room/{quote(name, safe='')}"))
        token = parse_qs(location.query)["modal_session_token"][0]
        room_path = f"/room/{quote(quote(name, safe=URI_COMPONENT_SAFE), safe=URI_COMPONENT_SAFE)}"
        assert location.fragment == room_path, location.fragment
        return f"{location.scheme}://{location.netloc}", token, location.fragment

    blank = urlparse(redirect_location(f"{lobby_url}/room/"))
    assert blank.fragment.startswith("/room/The "), blank.fragment
    print("A blank room path redirected to a generated room")

    name = f"test-{secrets.token_hex(3)}"
    server_url, token, _ = join(name)
    assert join(name)[:2] == (server_url, token), "joining the same room used a different session"
    print(f"Both joins of {name!r} used the same session")

    request = urllib.request.Request(server_url, headers={"Modal-Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request) as response:
        assert "Curvytron" in response.read().decode()
    try:
        urllib.request.urlopen(server_url)
        raise AssertionError("server accepted a request without a session token")
    except urllib.error.HTTPError as error:
        assert error.code == 401, f"expected 401 without a session token, got {error.code}"
    print("The room server served the session and rejected tokenless access")

    with urllib.request.urlopen(f"{lobby_url}/rooms") as response:
        listed = json.loads(response.read())
    assert any(room["name"] == name for room in listed), f"{name!r} was missing from /rooms"
    print("The lobby listed the newly joined room")

    spaced_name = f"Fun room {secrets.token_hex(2)}!%/雪"
    assert join(spaced_name)[:2] == join(spaced_name)[:2]
    print(f"Room {spaced_name!r} retained its name through the redirect")

    room.Room.sessions.terminate(token)
    _, next_token, _ = join(name)
    assert next_token != token, "rejoining after session termination reused its token"
    print("Rejoining after session termination started a new session")
