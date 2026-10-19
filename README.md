# curvytron

A public multiplayer demo of [Modal Sticky Sessions](https://modal.com/docs/guide/sticky-sessions), running [Curvytron](https://github.com/Curvytron/curvytron) (MIT), a browser clone of _Achtung, die Kurve!_

Curvytron's Node.js server keeps each room's game state in process memory, so every player in a room must reach the same container. The lobby is a Modal web function; it maps room names to session tokens in a Modal Dict, opens rooms on sessioned `Room` servers, and redirects players to the server. Share links as `<lobby>/room/<name>`.

- The room server is built from a pinned upstream commit with a small patch for lobby discovery and room creation.
- Each container hosts up to 8 rooms (sessions), with at most 2 containers. Routing and compute are pinned to `us-east`.
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
