import assert from 'node:assert/strict';
import test from 'node:test';
import { layout, MAX_GUESTS, MIN_GUESTS, SETTINGS, thumbShapes } from '../frontend/js/rooms.js';

const overlap = (a, b) => a.x < b.x + b.w - 1e-8 && b.x < a.x + a.w - 1e-8
  && a.y < b.y + b.h - 1e-8 && b.y < a.y + a.h - 1e-8;
function inside(box) {
  for (const v of [box.x, box.y, box.w, box.h]) assert.ok(Number.isFinite(v));
  assert.ok(box.x >= 0 && box.y >= 0 && box.w > 0 && box.h > 0);
  assert.ok(box.x + box.w <= 100 + 1e-8 && box.y + box.h <= 100 + 1e-8);
}

test('every room has an uncropped full-stage gallery without slides for one to three guests and VIP', () => {
  assert.equal(MIN_GUESTS, 1); assert.equal(MAX_GUESTS, 3);
  for (const setting of SETTINGS) for (const n of [1, 2, 3, 4]) {
    const plan = layout(setting.id, n, false);
    assert.equal(plan.slide, null); assert.equal(plan.seats.length, n);
    plan.seats.forEach(inside);
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      assert.equal(overlap(plan.seats[i], plan.seats[j]), false);
    }
    assert.deepEqual(plan.seats, layout('video', n, false).seats);
  }
});

test('adaptive deck layouts keep every guest and slide inside the stage without overlap', () => {
  for (const setting of SETTINGS) for (const n of [1, 2, 3, 4]) {
    const plan = layout(setting.id, n, true);
    inside(plan.slide); assert.equal(plan.seats.length, n);
    for (const seat of plan.seats) { inside(seat); assert.equal(overlap(seat, plan.slide), false); }
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      assert.equal(overlap(plan.seats[i], plan.seats[j]), false);
    }
  }
});

test('fewer guests grow into available room space and setting thumbnails retain the supported maximum', () => {
  for (const setting of SETTINGS) for (const deck of [false, true]) {
    const area = (n) => { const seat = layout(setting.id, n, deck).seats[0]; return seat.w * seat.h; };
    assert.ok(area(1) >= area(2)); assert.ok(area(2) >= area(3));
  }
  for (const setting of SETTINGS) {
    const shapes = thumbShapes(setting.id);
    const guestColors = shapes.filter((s) => typeof s.c === 'string' && s.c.startsWith('oklch(0.74'));
    assert.equal(guestColors.length, MAX_GUESTS);
  }
});
