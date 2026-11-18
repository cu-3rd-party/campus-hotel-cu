import { SPECS } from "./labels.js";

const choices = (value) => Array.isArray(value) ? value : String(value || "").split(",").filter(Boolean);

export function compareHabits(me, person) {
  if (!me || me.id === person.id || me.campus !== person.campus || me.gender !== person.gender) return null;
  const fields = new Map();
  let matched = 0;

  for (const [, , labelFor, key] of SPECS) {
    const mine = labelFor(me);
    if (!mine || !labelFor(person) || me[key] === "any" || person[key] === "any") continue;
    const same = key === "cooking"
      ? choices(me.cooking).some((choice) => choices(person.cooking).includes(choice))
      : me[key] === person[key];
    fields.set(key, { same, mine });
    if (same) matched += 1;
  }

  return fields.size ? {
    fields, matched,
    percent: Math.round(matched * 100 / fields.size),
  } : null;
}
