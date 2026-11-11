# curvytron

A public multiplayer demo of [Modal Sticky Sessions](https://modal.com/docs/guide/sticky-sessions), running [Curvytron](https://github.com/Curvytron/curvytron) (MIT), a browser clone of _Achtung, die Kurve!_

Curvytron's Node.js server keeps each room's game state in process memory, so every player in a room must reach the same container. The lobby is a Modal web function; it maps room names to session tokens in a Modal Dict, opens rooms on sessioned `Room` servers, and redirects players to the server. Share links as `<lobby>/room/<name>`.

- The room server is built from a pinned upstream commit with a small patch for lobby discovery and room creation.
- Each container hosts up to 8 rooms (sessions), with at most 2 containers. Routing is pinned to `us-east`, and compute to the Ashburn metro (AWS `us-east-1`, GCP `us-east4`, OCI `us-ashburn-1`, and other Ashburn regions).
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

`.github/workflows/deploy.yml` deploys on every push to `main`, and can also be run manually. It needs the repository secrets `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` for the target workspace. It deploys to the `main` environment unless the repository variable `MODAL_ENVIRONMENT` is set. The lobby is served at `kathir-world-is-better.modal.dev` unless the repository variable `CURVYTRON_DOMAIN` is set; locally, set `CURVYTRON_DOMAIN` when deploying to use a custom domain.

## AI opponent

Rooms can add an AI opponent for 1v1 games: the room master clicks **Play vs AI** while alone in a room, without teams. The AI is a policy trained with PPO self-play in the curvyrl project, exported to ONNX (the overnight CNN, update 4017; 8.4 MB). It runs on the room container's CPU with `onnxruntime-node`, at about 1 ms per decision, so no GPU is needed.

- **`src/bot/`**: the bot. `obs.cjs` builds the policy's observation from the live server game; it is a port of the training env's observation and is parity-tested against it in curvyrl. `bot.cjs` runs the model, deciding every 4 frames as in training and only sending a move when it changes. `model/` holds `model.onnx` plus `meta.json` (observation parameters).
- **Hooks in `src/curvytron.patch`**:
  - `src/server/core/CurvyrlBots.js` loads the bot once and creates one per bot player.
  - `room:bot:add` / `room:bot:remove` socket events. The bot is a player owned by the requesting client, so it leaves with them.
  - `Game` drives bot avatars each frame, and `player:move` from clients is ignored for bot avatars.
  - Clients get a `bot` flag on players and don't bind controls to them.
  - If more players join after the AI was added, it plays against the nearest living opponent. It was only trained for 1v1, so expect weaker play.
- **Updating the model**: in curvyrl, run `python -m curvyrl.deploy.export CKPT --out <this repo>/src/bot/model`. If the observation code changed, copy `bot.cjs`/`obs.cjs` too.
- **Smoke test** (local server on :8020): `node bot/smoke.cjs ws://localhost:8020 30000` from the built Curvytron directory. It adds a player that never steers plus the AI, and passes if the AI steers and wins every round.
