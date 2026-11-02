// The rules and the computer player for tic-tac-toe (reference solution for the "tictactoe_js" exercise).
// A board is an array of 9 cells (index 0 is top-left, 8 is bottom-right, read row by row); each cell is "X", "O" or null (empty).
// ui.js draws the board in the browser and calls these functions; the hidden tests load this file with Node.js.

// All 8 ways to win, as lists of three cell positions: 3 rows, 3 columns, 2 diagonals.
const LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];

// Who has won? Takes a board; returns "X" or "O" if that player has three in a line,
// "draw" if the board is full with no winner, or null if the game is still going.
function winner(board) {
  for (const [a, b, c] of LINES) {
    // The first cell must be non-empty and equal to the other two.
    if (board[a] && board[a] === board[b] && board[a] === board[c]) return board[a];
  }
  // No line won: it is a draw only when no cell is empty (every cell is truthy).
  return board.every((c) => c) ? "draw" : null;
}

// Whose turn is it? X always goes first, so if both have placed the same number of marks it is X's turn, otherwise O's.
function nextPlayer(board) {
  const x = board.filter((c) => c === "X").length;
  const o = board.filter((c) => c === "O").length;
  return x === o ? "X" : "O";
}

// "Minimax": the computer tries every possible future game and picks the best result, assuming both sides play well.
// score() rates a board from the point of view of player `me` (the one choosing a move).
// `depth` is how many moves ahead we are. A win is worth 10 minus depth (so quicker wins score higher),
// a loss is depth minus 10 (so slower losses are less bad), and a draw is 0.
function score(board, me, depth) {
  const w = winner(board);
  if (w === me) return 10 - depth;
  if (w === "draw") return 0;
  if (w) return depth - 10;
  // Game not over: try every empty cell for whoever's turn it is. On my turn I pick the highest score (max),
  // on the opponent's turn I assume they pick the lowest score for me (min).
  const turn = nextPlayer(board);
  let best = turn === me ? -Infinity : Infinity;
  for (let i = 0; i < 9; i++) {
    if (board[i]) continue;
    // Place a mark, look at what follows, then take the mark back (undo) so the board is left as we found it.
    board[i] = turn;
    const s = score(board, me, depth + 1);
    board[i] = null;
    best = turn === me ? Math.max(best, s) : Math.min(best, s);
  }
  return best;
}

// The computer's choice: returns the cell number (0-8) of the best move for the player whose turn it is,
// or -1 if the game is already over. Ties go to the lowest cell number. Works on a copy, so the caller's board is not changed.
function bestMove(board) {
  if (winner(board)) return -1;
  const me = nextPlayer(board);
  const b = board.slice();
  let best = -Infinity, move = -1;
  for (let i = 0; i < 9; i++) {
    if (b[i]) continue;
    b[i] = me;
    const s = score(b, me, 1);
    b[i] = null;
    // ">" (not ">=") keeps the first of equally good moves.
    if (s > best) { best = s; move = i; }
  }
  return move;
}

// In a browser there is no "module", so this line does nothing there (the functions are simply global).
// In Node.js (the tests) it exports the functions so the test file can use them.
if (typeof module !== "undefined") module.exports = { winner, nextPlayer, bestMove };
