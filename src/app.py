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


ASSETS_DIR = "/assets"
CURVYTRON_ASSETS_URL = f"https://raw.githubusercontent.com/Curvytron/curvytron/{CURVYTRON_COMMIT}/web/images"

launcher_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl")
    .uv_pip_install("fastapi[standard]==0.116.1")
    .run_commands(
        f"mkdir -p {ASSETS_DIR}",
        f"curl -fsSL {CURVYTRON_ASSETS_URL}/logo.svg -o {ASSETS_DIR}/logo.svg",
        f"curl -fsSL {CURVYTRON_ASSETS_URL}/favicon.png -o {ASSETS_DIR}/favicon.png",
    )
)


@app.function(image=launcher_image)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def ui():
    import html
    import secrets

    from fastapi import FastAPI
    from fastapi.responses import FileResponse, HTMLResponse

    web_app = FastAPI()

    def page(body: str) -> HTMLResponse:
        return HTMLResponse(PAGE_HTML.format(style=PAGE_CSS, body=body))

    @web_app.get("/")
    async def index():
        return page(CREATE_ROOM_HTML)

    @web_app.get("/logo.svg")
    async def logo():
        return FileResponse(f"{ASSETS_DIR}/logo.svg", media_type="image/svg+xml")

    @web_app.get("/favicon.png")
    async def favicon():
        return FileResponse(f"{ASSETS_DIR}/favicon.png", media_type="image/png")

    @web_app.post("/new")
    async def new_room():
        session = await Curvytron.sessions.start.aio(idle_timeout=ROOM_IDLE_TIMEOUT)
        server_url = await Curvytron.get_url.aio()
        # Rooms on a container share one Curvytron process, so names must not collide.
        room = f"room-{secrets.token_hex(3)}"
        invite = f"{server_url}/?modal_session_token={session.token}#/room/{room}"
        body = INVITE_HTML.format(invite=html.escape(invite), room=room, idle_minutes=ROOM_IDLE_TIMEOUT // MINUTES)
        return page(body)

    return web_app


PAGE_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Curvytron on Modal</title>
    <link rel="icon" type="image/png" href="favicon.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lato:wght@300;400;700&display=swap">
    <style>{style}</style>
  </head>
  <body>
    <header>
      <a class="logo" href="./">
        <img src="logo.svg" alt="">
        <span class="brand">Curvytron</span>
      </a>
      <p class="tagline">Multiplayer on Modal</p>
    </header>
    <main>{body}</main>
    <footer>
      <a href="https://github.com/Curvytron/curvytron">Curvytron</a> by Gameo, MIT licensed.
      Hosted on Modal with <a href="https://modal.com/docs/guide/sticky-sessions">Sticky Sessions</a>.
    </footer>
  </body>
</html>
"""

PAGE_CSS = """
:root {
  color-scheme: light;
  --bg: #f3f3f3;
  --panel: #fff;
  --text: #666;
  --text-strong: #444;
  --muted: #8a8a8a;
  --from: #ff8069;
  --to: #ff6e90;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
  font: 300 18px/1.75 Lato, "Helvetica Neue", Helvetica, sans-serif;
}
a { color: inherit; }
header {
  padding: 28px 16px 22px;
  border-bottom: 10px solid var(--panel);
  background: linear-gradient(var(--from), var(--to));
  color: #fff;
  text-align: center;
}
.logo { display: inline-flex; flex-direction: column; align-items: center; text-decoration: none; }
.logo img { width: 96px; height: 96px; }
.brand { font-size: 26px; font-weight: 400; line-height: 46px; letter-spacing: 0.08em; text-transform: uppercase; }
.tagline { margin: 0; font-size: 15px; letter-spacing: 0.04em; opacity: 0.9; }
main { flex: 1; width: 100%; max-width: 600px; margin: 48px auto; padding: 0 16px; text-align: center; }
h2 { margin: 0 0 10px; font-size: 30px; font-weight: 300; line-height: 1.4; text-transform: uppercase; }
p { margin: 0 0 10px; }
.lead { font-size: 20px; }
.hint { font-size: 15px; color: var(--muted); }
.actions { display: flex; justify-content: center; margin: 32px 0; }
.btn {
  display: inline-block;
  padding: 0;
  border: 0;
  background: linear-gradient(90deg, var(--from), var(--to));
  color: #fff;
  font: 400 22px/1 Lato, "Helvetica Neue", Helvetica, sans-serif;
  letter-spacing: 0.05em;
  text-decoration: none;
  text-transform: uppercase;
  cursor: pointer;
  transform: skew(-10deg);
  transition: transform 0.1s linear, filter 0.1s linear;
  user-select: none;
}
.btn span { display: block; padding: 16px 36px; transform: skew(10deg); }
.btn:hover { filter: brightness(1.05); transform: skew(-10deg) translateY(-2px); }
.btn:focus-visible { outline: 3px solid var(--text-strong); outline-offset: 4px; }
.invite { display: flex; margin: 32px 0 0; overflow: hidden; background: var(--panel); }
.invite input {
  flex: 1;
  min-width: 0;
  padding: 14px 16px;
  border: 0;
  background: var(--panel);
  color: var(--text-strong);
  font: 300 16px Lato, "Helvetica Neue", Helvetica, sans-serif;
}
.invite .btn { margin-right: -10px; border-left: 10px solid var(--bg); font-size: 18px; }
.invite .btn span { padding: 14px 30px 14px 22px; }
.invite .btn:focus-visible { outline: none; }
.invite:has(.btn:focus-visible) { outline: 3px solid var(--text-strong); outline-offset: 4px; }
.room { color: var(--text-strong); font-weight: 700; }
.loader { display: none; margin: 24px 0; }
.loading .create { display: none; }
.loading .loader { display: block; }
.loader svg { width: 260px; max-width: 100%; height: auto; }
.trail {
  fill: none;
  stroke-width: 6;
  stroke-linecap: round;
  stroke-dasharray: 100;
  stroke-dashoffset: 100;
  animation: draw 2.4s ease-in-out infinite;
}
.trail:nth-child(2) { animation-delay: 0.3s; }
.trail:nth-child(3) { animation-delay: 0.6s; }
@keyframes draw {
  0% { stroke-dashoffset: 100; opacity: 1; }
  60% { stroke-dashoffset: 0; opacity: 1; }
  85% { stroke-dashoffset: 0; opacity: 0; }
  100% { stroke-dashoffset: 100; opacity: 0; }
}
.status { font-size: 20px; color: var(--text-strong); }
.elapsed { font-variant-numeric: tabular-nums; }
footer { padding: 20px 16px; background: #e2e2e2; color: var(--muted); font-size: 14px; text-align: center; }
@media (prefers-reduced-motion: reduce) {
  .trail { animation: none; stroke-dashoffset: 0; }
  .btn, .btn:hover { transition: none; transform: skew(-10deg); }
}
"""

CREATE_ROOM_HTML = """
    <form id="create" method="post" action="new">
      <p class="lead">Create a room and share its invite link with your friends.</p>
      <div class="actions create">
        <button class="btn" type="submit"><span>Create a room</span></button>
      </div>
      <div class="loader" role="status" aria-live="polite">
        <svg viewBox="0 0 260 110" aria-hidden="true">
          <path class="trail" pathLength="100" stroke="#36b0bb" d="M10 80 C 60 10, 110 10, 140 55 S 210 100, 250 30"/>
          <path class="trail" pathLength="100" stroke="#ff6e90" d="M10 30 C 50 90, 100 100, 130 60 S 200 5, 250 75"/>
          <path class="trail" pathLength="100" stroke="#4b5ff4" d="M10 55 C 70 55, 90 20, 130 25 S 220 90, 250 55"/>
        </svg>
        <p class="status">Starting a game server&hellip; <span class="elapsed">0s</span></p>
        <p class="hint">A new container can take up to a minute to boot.</p>
      </div>
    </form>
    <script>
      const form = document.getElementById("create");
      const button = form.querySelector("button");
      const elapsed = form.querySelector(".elapsed");
      let timer;
      form.addEventListener("submit", () => {
        const started = Date.now();
        form.classList.add("loading");
        button.disabled = true;
        timer = setInterval(() => {
          elapsed.textContent = `${Math.floor((Date.now() - started) / 1000)}s`;
        }, 250);
      });
      window.addEventListener("pageshow", (event) => {
        if (!event.persisted) return;
        clearInterval(timer);
        form.classList.remove("loading");
        button.disabled = false;
        elapsed.textContent = "0s";
      });
    </script>
"""

INVITE_HTML = """
    <h2>Your room is ready</h2>
    <p class="lead">Send this invite link to your friends, then join using the same link.</p>
    <div class="invite">
      <input id="invite" value="{invite}" readonly aria-label="Invite link">
      <button id="copy" class="btn" type="button"><span>Copy</span></button>
    </div>
    <div class="actions">
      <a id="play" class="btn" href="{invite}"><span>Play</span></a>
    </div>
    <p class="hint">Room <span class="room">{room}</span> closes once it has been empty for
       {idle_minutes} minutes.</p>
    <script>
      const invite = document.getElementById("invite");
      const copy = document.getElementById("copy");
      invite.addEventListener("focus", () => invite.select());
      copy.addEventListener("click", async () => {{
        await navigator.clipboard.writeText(invite.value);
        copy.querySelector("span").textContent = "Copied!";
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
    invite = urlparse(html.unescape(re.search(r'id="play" class="btn" href="([^"]+)"', page).group(1)))
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
