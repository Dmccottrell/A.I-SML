const assert = require("assert");
const path = require("path");
const { winner, nextPlayer, bestMove } = require(path.join(__dirname, "game.js"));
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log("PASS " + name); } catch (e) { failed++; console.log("FAIL " + name + ": " + e.message); }
}
const B = (s) => s.split("").map((c) => (c === "." ? null : c));

test("winner", () => {
  assert.strictEqual(winner(B("XXX.OO...")), "X");
  assert.strictEqual(winner(B("XO.XO..O.")), "O");
  assert.strictEqual(winner(B("O.X.X.X.O")), "X");
  assert.strictEqual(winner(B("XOXXOOOXX")), "draw");
  assert.strictEqual(winner(B(".........")), null);
  assert.strictEqual(winner(B("XO.......")), null);
});
test("nextPlayer", () => {
  assert.strictEqual(nextPlayer(B(".........")), "X");
  assert.strictEqual(nextPlayer(B("X........")), "O");
  assert.strictEqual(nextPlayer(B("XO.......")), "X");
});
test("takes the win", () => {
  assert.strictEqual(bestMove(B("OO.XX.X..")), 2);
});
test("blocks", () => {
  assert.strictEqual(bestMove(B("XX..O....")), 2);
});
test("game over", () => {
  assert.strictEqual(bestMove(B("XXXOO....")), -1);
});
test("never loses as O", () => {
  function explore(board) {
    const w = winner(board);
    if (w) { assert.notStrictEqual(w, "X", "O lost: " + board.map((c) => c || ".").join("")); return; }
    if (nextPlayer(board) === "O") {
      const m = bestMove(board);
      assert.ok(m >= 0 && !board[m], "bad move");
      board[m] = "O"; explore(board); board[m] = null;
    } else {
      for (let i = 0; i < 9; i++) if (!board[i]) { board[i] = "X"; explore(board); board[i] = null; }
    }
  }
  explore(B("........."));
});
console.log(`passed ${passed} of ${passed + failed}`);
process.exit(failed ? 1 : 0);
