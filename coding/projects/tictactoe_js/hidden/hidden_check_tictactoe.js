// Hidden checks for the "tictactoe_js" coding exercise. The agent never sees this file; it is run afterwards with Node.js
// to decide whether the agent's game.js works. It prints PASS/FAIL per test and exits with code 1 if any failed.
const assert = require("assert");
const path = require("path");
// Load the agent's game.js that sits next to this file.
const { winner, nextPlayer, bestMove } = require(path.join(__dirname, "game.js"));
let passed = 0, failed = 0;
// A tiny test runner: run fn; if it throws (a failed assert), count and print a FAIL line, otherwise a PASS line.
function test(name, fn) {
  try { fn(); passed++; console.log("PASS " + name); } catch (e) { failed++; console.log("FAIL " + name + ": " + e.message); }
}
// Helper: write a board as a 9-character string, "." for empty. B("XO.......") gives ["X","O",null,...].
const B = (s) => s.split("").map((c) => (c === "." ? null : c));

// winner() should find rows, columns, diagonals, draws, and say null when the game is not over.
test("winner", () => {
  assert.strictEqual(winner(B("XXX.OO...")), "X");     // top row
  assert.strictEqual(winner(B("XO.XO..O.")), "O");     // middle column
  assert.strictEqual(winner(B("O.X.X.X.O")), "X");     // anti-diagonal
  assert.strictEqual(winner(B("XOXXOOOXX")), "draw");  // full board, no line
  assert.strictEqual(winner(B(".........")), null);
  assert.strictEqual(winner(B("XO.......")), null);
});
// X moves first, then they alternate.
test("nextPlayer", () => {
  assert.strictEqual(nextPlayer(B(".........")), "X");
  assert.strictEqual(nextPlayer(B("X........")), "O");
  assert.strictEqual(nextPlayer(B("XO.......")), "X");
});
// O has two in the top row, so cell 2 wins at once.
test("takes the win", () => {
  assert.strictEqual(bestMove(B("OO.XX.X..")), 2);
});
// X threatens the top row (cells 0 and 1); O (to move) must block at cell 2.
test("blocks", () => {
  assert.strictEqual(bestMove(B("XX..O....")), 2);
});
// X has already won, so there is no move to make: -1.
test("game over", () => {
  assert.strictEqual(bestMove(B("XXXOO....")), -1);
});
// Plays every possible game where X tries every move and O answers with bestMove; X must never win.
test("never loses as O", () => {
  function explore(board) {
    const w = winner(board);
    // Game finished: fail if X won, and stop exploring this branch.
    if (w) { assert.notStrictEqual(w, "X", "O lost: " + board.map((c) => c || ".").join("")); return; }
    if (nextPlayer(board) === "O") {
      // O's turn: the computer's move must be a real empty cell.
      const m = bestMove(board);
      assert.ok(m >= 0 && !board[m], "bad move");
      board[m] = "O"; explore(board); board[m] = null;
    } else {
      // X's turn: try every empty cell in turn (undoing each one after) so all X strategies are covered.
      for (let i = 0; i < 9; i++) if (!board[i]) { board[i] = "X"; explore(board); board[i] = null; }
    }
  }
  explore(B("........."));
});
console.log(`passed ${passed} of ${passed + failed}`);
// A non-zero exit code tells whoever ran this file that something failed.
process.exit(failed ? 1 : 0);
