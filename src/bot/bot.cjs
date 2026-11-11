'use strict';

/**
 * Server-side Curvytron AI player backed by an exported ONNX policy (see curvyrl/deploy/export.py).
 *
 *   const { CurvyBot } = require('curvyrl-bot');
 *   CurvyBot.installHooks({ Bonus });                 // once, after the server classes are defined
 *   const bot = await CurvyBot.load('/path/to/model'); // model.onnx + meta.json
 *   bot.attach(game, avatar);                         // on game start
 *   bot.onFrame();                                    // from the game loop, after game.update()
 *
 * Like in training, the bot decides every `frames_per_step` frames and only sends a move when it changes
 * (what the browser client does). Inference is async (~1 ms on CPU); the move lands within the next frame.
 */

const fs = require('node:fs');
const path = require('node:path');
const { observe } = require('./obs.cjs');

class CurvyBot {
    static async load(dir) {
        const ort = require('onnxruntime-node');
        const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'));
        const session = await ort.InferenceSession.create(path.join(dir, 'model.onnx'));
        return new CurvyBot(meta, session, ort);
    }

    /** Record when each bonus was applied so its remaining time can be observed (server timers are opaque). */
    static installHooks({ Bonus }) {
        if (Bonus.prototype.__curvyrlHooked) { return; }
        const applyTo = Bonus.prototype.applyTo;
        Bonus.prototype.applyTo = function (avatar, game) {
            this.__appliedAt = Date.now();
            return applyTo.call(this, avatar, game);
        };
        Bonus.prototype.__curvyrlHooked = true;
    }

    static timeLeft(bonus) {
        if (!bonus.duration || bonus.__appliedAt === undefined) { return null; }
        return Math.max(bonus.duration - (Date.now() - bonus.__appliedAt), 0);
    }

    constructor(meta, session, ort) {
        this.meta = meta;
        this.session = session;
        this.ort = ort;
        this.game = null;
    }

    attach(game, avatar) {
        this.game = game;
        this.avatar = avatar;
        this.frames = 0;
        this.decisions = 0;
        this.lastMove = 0;
        this.busy = false;
    }

    /** Avatars in player order with the opponent(s) after the bot, as the env sees them. */
    avatarsInOrder() {
        return this.game.avatars.items;
    }

    observation() {
        const avatars = this.avatarsInOrder();
        return observe(this.meta, this.game, avatars, avatars.indexOf(this.avatar), this.decisions, CurvyBot.timeLeft);
    }

    async act(obs) {
        const S = this.meta.image_size;
        const feeds = { vec: new this.ort.Tensor('float32', obs.vec, [1, obs.vec.length]) };
        if (obs.img) { feeds.img = new this.ort.Tensor('uint8', obs.img, [1, S, S]); }
        const { logits } = await this.session.run(feeds);
        const l = logits.data;
        let best = 0;
        for (let k = 1; k < l.length; k++) { if (l[k] > l[best]) { best = k; } }
        return best; // 0 left, 1 straight, 2 right
    }

    onFrame() {
        if (!this.game || !this.game.inRound || !this.avatar.alive) { return; }
        if (this.frames++ % this.meta.frames_per_step !== 0 || this.busy) { return; }
        const obs = this.observation();
        this.decisions++;
        this.busy = true;
        this.act(obs).then((action) => {
            this.busy = false;
            const move = action - 1;
            if (move !== this.lastMove && this.avatar.alive) {
                this.lastMove = move;
                this.avatar.updateAngularVelocity(move);
            }
        }, (error) => { this.busy = false; console.error('curvyrl bot inference failed:', error); });
    }

    /** Call when a new round starts. */
    newRound() {
        this.frames = 0;
        this.decisions = 0;
        this.lastMove = 0;
    }
}

module.exports = { CurvyBot, observe };
