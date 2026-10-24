// The presentation room uses backend-controlled speech; the native voice lab stays separate.
import { connect, getSession, isMock } from '/js/api.js';
import { createPlayer } from '/js/audio.js';
import { playMock } from '/js/mock_player.js';
import { connectVoice } from '/js/voice.js';
import { createRoomView } from '/js/room_view.js?v=optimized-room-1';
import { bootRoom } from '/js/room_controller.js';

const view = createRoomView(document);
await bootRoom({ view, connect, getSession, isMock, createPlayer, playMock, connectVoice,
  fetch: window.fetch.bind(window), location: window.location, window,
}).catch((error) => view.error(error.message || 'The presentation room could not load.'));
