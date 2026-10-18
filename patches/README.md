# Curvytron patches

Applied in order with `git apply` on top of the pinned upstream commit in `src/app.py`.

| Patch | What it does |
| --- | --- |
| `0001` | Joining an unknown room creates it, so invite links go straight into a fresh room. |
| `0002` | Mobile: no text selection, callouts or browser gestures on the game; touch input uses non-passive listeners (a held turn no longer triggers the long-press context menu, which froze the animation) and works on browsers without `document.createTouch`; the round recap shows the scoreboard. |
| `0003` | Client-side prediction with rollback: inputs carry a sequence number that the server echoes in position updates; the client rewinds to the latest authoritative state, replays unacknowledged inputs over one round trip, and smooths corrections. |
| `0004` | While a game runs, position/angle updates go over an unreliable, unordered WebRTC data channel and inputs over a reliable one, negotiated over the WebSocket, which stays the fallback. Set `CURVYTRON_WEBRTC=0` to disable, `CURVYTRON_ICE_SERVERS` to change STUN/TURN servers. |
| `0005` | Offline play: a service worker caches the app; offline (or with `?offline`), the game server runs in a Web Worker in the page. |

To change them, check out the pinned commit, `git am patches/*.patch`, commit on top, and regenerate with `git format-patch <pinned commit>..HEAD -o patches --no-signature`.
