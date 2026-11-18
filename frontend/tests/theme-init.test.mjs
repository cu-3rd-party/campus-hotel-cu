import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";

const script = readFileSync(new URL("../public/theme-init.js", import.meta.url), "utf8");

function initialTheme(saved, prefersDark, storageBlocked = false) {
  let theme;
  runInNewContext(script, {
    localStorage: { getItem() {
      if (storageBlocked) throw new Error("Storage blocked");
      return saved;
    } },
    window: { matchMedia: () => ({ matches: prefersDark }) },
    document: { documentElement: { setAttribute: (key, value) => {
      assert.equal(key, "data-theme");
      theme = value;
    } } },
  });
  return theme;
}

test("early render uses the device theme without a valid manual choice", () => {
  assert.equal(initialTheme(null, false), "light");
  assert.equal(initialTheme(null, true), "dark");
  assert.equal(initialTheme("system", true), "dark");
  assert.equal(initialTheme("invalid", false), "light");
  assert.equal(initialTheme(null, true, true), "dark");
});

test("early render respects a saved light or dark choice over the device theme", () => {
  assert.equal(initialTheme("light", true), "light");
  assert.equal(initialTheme("dark", false), "dark");
});
