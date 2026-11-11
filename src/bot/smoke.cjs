'use strict';
// End-to-end smoke test: a scripted browser-like client plays a passive human against the AI on a local server.
const WebSocket = require('faye-websocket');

const url = process.argv[2] || 'ws://localhost:8020';
const ws = new WebSocket.Client(url, ['websocket']);
let callId = 0;
const callbacks = {};
const players = {};
const roundWinners = [];
let botAngles = 0, human = null, bot = null;

function send(name, data) {
    return new Promise((resolve) => {
        const id = callId++;
        callbacks[id] = resolve;
        ws.send(JSON.stringify([[name, data, id]]));
    });
}

ws.on('message', (e) => {
    for (const ev of JSON.parse(e.data)) {
        const [name, data] = ev;
        if (typeof name !== 'string') { if (callbacks[name]) { callbacks[name](data); delete callbacks[name]; } continue; }
        if (name === 'room:join') { players[data.player.id] = data.player; }
        if (name === 'room:game:start') { setTimeout(() => ws.send(JSON.stringify([['ready']])), 500); }
        if (name === 'angle' && bot && data[0] === bot.id) { botAngles++; }
        if (name === 'round:end') { roundWinners.push(data); }
    }
});

ws.on('open', async () => {
    const room = 'ai-smoke-' + Date.now();
    console.log('join', JSON.stringify(await send('room:join', { name: room })));
    console.log('add human', JSON.stringify(await send('player:add', { name: 'Human', color: '#ff4136' })));
    console.log('add bot', JSON.stringify(await send('room:bot:add', {})));
    await new Promise((r) => setTimeout(r, 300));
    human = Object.values(players).find((p) => p.name === 'Human');
    bot = Object.values(players).find((p) => p.bot);
    console.log('players', Object.values(players).map((p) => `${p.name}(bot=${p.bot}, ready=${p.ready})`).join(', '));
    console.log('ready', JSON.stringify(await send('room:ready', { player: human.id })));
    setTimeout(() => {
        const botWins = roundWinners.filter((w) => w === bot.id).length;
        console.log(`rounds ended: ${roundWinners.length}, AI won ${botWins}; AI angle events: ${botAngles}`);
        process.exit(roundWinners.length > 0 && botWins === roundWinners.length && botAngles > 0 ? 0 : 1);
    }, Number(process.argv[3] || 30000));
});
