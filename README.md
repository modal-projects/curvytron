# curvytron

A public multiplayer demo running [Curvytron](https://github.com/Curvytron/curvytron) (MIT), a browser clone of _Achtung, die Kurve!_, on [Modal](https://modal.com).

Curvytron's Node.js server keeps each room's game state in process memory, so it runs on a single always-on container (`min_containers=1`, `max_containers=1`) and everyone plays at the server's URL.

- The `Curvytron` Server is built from a pinned upstream commit plus the patches in [`patches/`](patches/README.md): room links create rooms on join, better mobile controls, client-side prediction, opponent ghosts, WebRTC game state, and offline play.
- Routing and compute are pinned to `us-east`.

## Quickstart

```bash
git clone https://github.com/modal-projects/curvytron.git
cd curvytron
uv sync
modal setup
```

### Commands

```bash
# check that the game is served
uv run modal run -m src.app

# serve with hot reload
uv run modal serve -m src.app

# deploy
uv run modal deploy -m src.app
```

## Deployment

`.github/workflows/deploy.yml` deploys on every push to `main`, and can also be run manually. It needs the repository secrets `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` for the target workspace. It deploys to the `main` environment unless the repository variable `MODAL_ENVIRONMENT` is set.
