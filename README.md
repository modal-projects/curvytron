# curvytron

A public multiplayer demo of [Modal Sticky Sessions](https://modal.com/docs/guide/sticky-sessions), running a [fork](https://github.com/KartikYZ/curvytron) of [Curvytron](https://github.com/Curvytron/curvytron) (MIT), a browser clone of _Achtung, die Kurve!_

Curvytron's Node.js server keeps each room's game state in process memory, so every player in a room must reach the same container. Rooms are shared as `<launcher>/room/<name>` links, and players play in Curvytron's own UI. The fork's lobby creates rooms through the launcher.

- The `ui` launcher has no page of its own. It keeps a room-to-session mapping in the `curvytron-rooms` Modal Dict, starts a session the first time a room is joined (or after its session has ended), opens the room on that session's container with the fork's `PUT /rooms/:name`, and redirects to `<server>/?modal_session_token=<token>#/room/<name>`. Modal exchanges the query parameter for a session cookie, and Curvytron's page and WebSocket are then routed to the room's container. `<launcher>/` redirects to a new room.
- The `Curvytron` Server is built from a pinned commit of the fork, with `CURVYTRON_LAUNCHER_URL` set to the launcher. Opening a room that doesn't exist on the current container, such as a server URL copied from another browser, lands in Curvytron's lobby.
- Each container hosts up to 10 rooms (sessions), with at most 2 containers. One container is always running, plus one buffer container. Routing and compute are pinned to `us-east`.
- A room's session ends after it has been empty for 5 minutes.

## Quickstart

```bash
git clone https://github.com/modal-projects/curvytron.git
cd curvytron
uv sync
modal setup
```

### Commands

```bash
# join a room through the launcher and check session routing
uv run modal run -m src.app

# serve with hot reload
uv run modal serve -m src.app

# deploy
uv run modal deploy -m src.app
```

## Deployment

`.github/workflows/deploy.yml` deploys on every push to `main`, and can also be run manually. It needs the repository secrets `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` for the target workspace. It deploys to the `main` environment unless the repository variable `MODAL_ENVIRONMENT` is set.
