'use strict';

/**
 * Observation builder for the server-side bot: a JS port of CurvyEnv.observe (curvyrl/env/core.py),
 * computed directly from a live Curvytron server Game. Parameters come from the exported meta.json.
 *
 * observe(meta, game, avatars, i, t, timeLeft) -> { vec: Float32Array(obs_dim), img: Uint8Array(S*S) | null }
 *   avatars:  avatars in player-index order (index i is the bot)
 *   t:        decisions made so far this round (the env's step counter)
 *   timeLeft: bonus -> ms remaining on its expiry timer (or null)
 */

const RAY_NONE = 0, RAY_OWN = 1, RAY_ENEMY = 2, RAY_WALL = 3;
const IMG_EMPTY = 0, IMG_OWN = 1, IMG_ENEMY = 2, IMG_WALL = 3, IMG_HEAD = 4, IMG_B_SELF = 5, IMG_B_ENEMY = 6, IMG_B_GAME = 7;

function floorMod(v, m) { return ((v % m) + m) % m; }

/** Occupancy grid (owner + 1 per cell) stamped from every trail body, oldest first (newer overwrite). */
function buildGrid(meta, game, avatars) {
    const res = meta.grid_res, size = game.size, G = Math.ceil(size * res);
    const grid = new Uint8Array(G * G);
    const seen = new Map();
    for (const island of game.world.islands.items) {
        for (const body of island.bodies.items) { seen.set(body.id, body); }
    }
    const R = Math.ceil(meta.stamp_radius_cap * res);
    for (const id of [...seen.keys()].sort((a, b) => a - b)) {
        const body = seen.get(id);
        const owner = avatars.indexOf(body.data);
        if (owner < 0) { continue; }
        const r = Math.min(body.radius, meta.stamp_radius_cap), lim = (r + 0.5 / res) ** 2;
        const bx = Math.floor(body.x * res), by = Math.floor(body.y * res);
        for (let dx = -R; dx <= R; dx++) {
            for (let dy = -R; dy <= R; dy++) {
                const cx = bx + dx, cy = by + dy;
                if (cx < 0 || cy < 0 || cx >= G || cy >= G) { continue; }
                if (((cx + 0.5) / res - body.x) ** 2 + ((cy + 0.5) / res - body.y) ** 2 <= lim) {
                    grid[cy * G + cx] = owner + 1;
                }
            }
        }
    }
    return { grid, G };
}

function lookup(meta, game, g, px, py) {
    const size = game.size, res = meta.grid_res;
    const inside = px >= 0 && px < size && py >= 0 && py < size;
    if (game.borderless) { px = floorMod(px, size); py = floorMod(py, size); }
    const wall = !inside && !game.borderless;
    const cx = Math.min(Math.max(Math.floor(px * res), 0), g.G - 1);
    const cy = Math.min(Math.max(Math.floor(py * res), 0), g.G - 1);
    return { wall, inside, cell: wall ? 0 : g.grid[cy * g.G + cx] };
}

function props(meta, a) {
    return [
        a.velocity / meta.base_velocity, a.radius / meta.base_radius, a.inverse ? 1 : 0, a.invincible ? 1 : 0,
        a.printing ? 1 : 0, a.directionInLoop ? 0 : 1, Math.sign(a.angularVelocity),
    ];
}

function observe(meta, game, avatars, i, t, timeLeft) {
    const size = game.size, P = avatars.length, me = avatars[i];
    const g = buildGrid(meta, game, avatars);
    const x = me.x, y = me.y, h = me.angle, ch = Math.cos(h), sh = Math.sin(h);
    const ego = (dx, dy) => [dx * ch + dy * sh, -dx * sh + dy * ch];
    const out = [];

    // Rays.
    for (const off of meta.ray_offsets) {
        const ang = h + off, ca = Math.cos(ang), sa = Math.sin(ang);
        let dist = meta.ray_max, kind = RAY_NONE;
        for (const d of meta.ray_dists) {
            const c = lookup(meta, game, g, x + ca * d, y + sa * d);
            if (c.wall || c.cell !== 0) {
                dist = d;
                kind = c.wall ? RAY_WALL : (c.cell === i + 1 ? RAY_OWN : RAY_ENEMY);
                break;
            }
        }
        out.push(dist / meta.ray_max, kind === RAY_OWN ? 1 : 0, kind === RAY_ENEMY ? 1 : 0, kind === RAY_WALL ? 1 : 0);
    }

    // Nearest map bonuses.
    const nTypes = meta.bonus_names.length;
    const bonuses = game.bonusManager.bonuses.items
        .map((b) => ({ b, dx: b.x - x, dy: b.y - y, d: Math.hypot(b.x - x, b.y - y) }))
        .sort((p, q) => p.d - q.d);
    for (let k = 0; k < meta.num_bonus_obs; k++) {
        const e = bonuses[k];
        const onehot = new Array(nTypes).fill(0);
        if (!e) { out.push(0, 0, 0, 0, ...onehot); continue; }
        const [f, r] = ego(e.dx, e.dy);
        onehot[meta.bonus_names.indexOf(e.b.constructor.name)] = 1;
        out.push(1, f / size, r / size, e.d / size, ...onehot);
    }

    // Self.
    out.push(x / size, y / size, ch, sh, ...props(meta, me), game.borderless ? 1 : 0, t / meta.max_steps);

    // Bonus timers: own stack, then the game stack.
    for (const stack of [me.bonusStack, game.bonusStack]) {
        const timers = new Array(nTypes).fill(0);
        for (const b of stack.bonuses.items) {
            const left = timeLeft(b);
            if (left !== null && left !== undefined) { timers[meta.bonus_names.indexOf(b.constructor.name)] += left / 10000; }
        }
        out.push(...timers);
    }

    // Opponents.
    for (let k = 1; k < P; k++) {
        const o = avatars[(i + k) % P];
        const dx = o.x - x, dy = o.y - y, [f, r] = ego(dx, dy), rel = o.angle - h;
        out.push(o.alive ? 1 : 0, f / size, r / size, Math.hypot(dx, dy) / size, Math.cos(rel), Math.sin(rel), ...props(meta, o));
    }

    if (out.length !== meta.obs_dim) { throw new Error(`obs has ${out.length} features, model expects ${meta.obs_dim}`); }
    return { vec: Float32Array.from(out), img: meta.obs_image ? image(meta, game, avatars, i, g) : null };
}

/** Egocentric IMG_* map (CurvyEnv.image): heading up, row 0 = ahead. */
function image(meta, game, avatars, i, g) {
    const S = meta.image_size, res = meta.image_res, me = avatars[i];
    const ch = Math.cos(me.angle), sh = Math.sin(me.angle);
    const img = new Uint8Array(S * S);
    const bonuses = game.bonusManager.bonuses.items;
    for (let r = 0; r < S; r++) {
        const fwd = (S / 2 - r - 0.5) / res;
        for (let c = 0; c < S; c++) {
            const right = (c - S / 2 + 0.5) / res;
            const wx = me.x + fwd * ch - right * sh, wy = me.y + fwd * sh + right * ch;
            const p = lookup(meta, game, g, wx, wy);
            let v = p.cell === 0 ? IMG_EMPTY : (p.cell === i + 1 ? IMG_OWN : IMG_ENEMY);
            if (p.wall) { v = IMG_WALL; }
            for (const b of bonuses) {
                if ((wx - b.x) ** 2 + (wy - b.y) ** 2 <= meta.bonus_radius ** 2) {
                    const affect = meta.bonus_affect[meta.bonus_names.indexOf(b.constructor.name)];
                    v = affect === 0 ? IMG_B_SELF : (affect === 1 ? IMG_B_ENEMY : IMG_B_GAME);
                    break;
                }
            }
            for (let k = 1; k < avatars.length; k++) {
                const o = avatars[(i + k) % avatars.length];
                if (o.alive && (wx - o.x) ** 2 + (wy - o.y) ** 2 <= (o.radius + 0.5 / res) ** 2) { v = IMG_HEAD; }
            }
            img[r * S + c] = v;
        }
    }
    return img;
}

module.exports = { observe, buildGrid, image };
