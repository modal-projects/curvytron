# curvytron

A public multiplayer demo of [Modal Sticky Sessions](https://modal.com/docs/guide/sticky-sessions), running [Curvytron](https://github.com/Curvytron/curvytron) (MIT), a browser clone of _Achtung, die Kurve!_

Curvytron's Node.js server keeps each room's game state in process memory, so every player in a room must reach the same container. The `ui` launcher starts one session per room and hands out an invite link of the form `<server>/?modal_session_token=<token>#/room/<name>`. Modal exchanges the query parameter for a session cookie, and the page and its WebSocket are then routed to the room's container.

- The `Curvytron` Server is built from a pinned upstream commit, with a one-line patch so that joining an unknown room creates it.
- Each container hosts up to 8 rooms (sessions), with at most 10 containers. Routing and compute are pinned to `us-east`.
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
# create a room through the launcher and check session routing
uv run modal run -m src.app

# serve with hot reload
uv run modal serve -m src.app

# deploy
uv run modal deploy -m src.app
```

## Deployment

`.github/workflows/deploy.yml` deploys on every push to `main`, and can also be run manually. It needs the repository secrets `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` for the target workspace. It deploys to the `main` environment unless the repository variable `MODAL_ENVIRONMENT` is set.
