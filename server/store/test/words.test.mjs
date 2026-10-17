// The word and link checks on what everyone sees (src/words.js).
import test from "node:test";
import assert from "node:assert/strict";
import { hasBlocked, refuse, squash } from "../src/words.js";

test("links are refused", () => {
  for (const bad of ["see https://x.y", "www.evil.com", "join discord.gg/abc", "a.com/x", "evil.xyz",
                     "javascript:alert(1)", "data:text/html,x", "file:///c:/x", "free.site", "go.shop"])
    assert.equal(refuse(bad), "no links", bad);
  for (const ok of ["lol", "i hate mondays.", "wait... what", "3.5 is fine"])
    assert.equal(refuse(ok), "", ok);
  assert.equal(refuse("x".repeat(281)), "too long");
  assert.equal(refuse(""), "empty");
  assert.equal(refuse("big bad-word here", ["badword"]), "not allowed");
});

test("blocked words can't hide behind accents, look-alike digits, dots or stretched letters", () => {
  assert.equal(squash("Ş.h-1 t"), "shit");
  for (const bad of ["b4dw0rd", "B A D W O R D", "bäd.wörd", "baaaddwooord", "my $tinky b@dword!"])
    assert.ok(hasBlocked(bad, ["badword"]), bad);
  for (const ok of ["a bad sword", "a good word", "bawd"])
    assert.ok(!hasBlocked(ok, ["badword"]), ok);
  assert.ok(!hasBlocked("anything", ["", " ", "..."]));       // an empty entry blocks nothing
});
