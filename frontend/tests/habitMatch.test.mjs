import assert from "node:assert/strict";
import test from "node:test";
import { compareHabits } from "../src/habitMatch.js";

const viewer = {
  id: 1, campus: "disk", gender: "male", sleep_schedule: "owl",
  noise: "quiet", cooking: ["self", "together"], shower: "any", smoking: "no",
};
const profile = { ...viewer, id: 2 };

test("habit score counts only mutually specified habits and accepts overlapping cooking preferences", () => {
  const result = compareHabits(viewer, {
    ...profile, smoking: "vape", cooking: ["together"], shower: "evening",
    noise: "", room_capacities: [4], open_room: { capacity: 4, spots_left: 2 },
  });
  assert.equal(result.matched, 2);
  assert.equal(result.fields.size, 3);
  assert.equal(result.percent, 67);
  assert.deepEqual(result.fields.get("smoking"), { mine: "Не курит", same: false });
  assert.equal(compareHabits(viewer, profile).percent, 100);
});

test("habit score is absent without comparable data, for oneself, or across feeds", () => {
  assert.equal(compareHabits(null, profile), null);
  assert.equal(compareHabits(viewer, viewer), null);
  assert.equal(compareHabits(viewer, { ...profile, campus: "cloud" }), null);
  assert.equal(compareHabits(viewer, { id: 2, campus: "disk", gender: "male", sleep_schedule: "any" }), null);
});
