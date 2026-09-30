// Run with: npm test
const test = require("node:test");
const assert = require("node:assert");
const { parseSkins, toCsv } = require("../../Src/DB/create_cs_skins.js");

const PAGE = `
<h4><a href="#">The Phoenix Collection</a></h4>
<table class="wikitable">
  <tr><th>Weapon</th><th>Skin</th></tr>
  <tr><td><a href="#">AK-47</a></td><td><span>Redline</span><span>Classified</span></td></tr>
  <tr><td><a href="#">Nova</a></td><td><span>Antique</span><span>Mil-Spec</span></td></tr>
</table>
<h4><a href="#">The Dust 2 Collection</a></h4>
<table class="wikitable">
  <tr><th>Weapon</th><th>Skin</th></tr>
  <tr><td><a href="#">Sawed-Off</a></td><td><span>Snake Camo</span><span>Consumer</span></td></tr>
</table>`;

test("pairs each table with its collection heading", () => {
  const skins = parseSkins(PAGE);

  assert.deepStrictEqual(
    skins.map(s => [s.collection, s.weapon, s.skin, s.quality]),
    [
      ["The Phoenix Collection", "AK-47", "Redline", "Classified"],
      ["The Phoenix Collection", "Nova", "Antique", "Mil-Spec"],
      ["The Dust 2 Collection", "Sawed-Off", "Snake Camo", "Consumer"],
    ],
  );
  assert.match(skins[0].marketUrl, /market_hash_name=AK-47%20%7C%20Redline%20\(Minimal%20Wear\)$/);
});

test("a blocked or changed page yields no skins", () => {
  assert.deepStrictEqual(parseSkins("<html><body>Access denied</body></html>"), []);
});

test("CSV escapes embedded quotes", () => {
  const csv = toCsv([{ collection: 'The "X" Collection', weapon: "AK-47", skin: "Redline", quality: "", marketUrl: "" }]);

  assert.strictEqual(csv.split("\n")[1], '"The ""X"" Collection","AK-47","Redline","",""');
});
