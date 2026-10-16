const LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];

function winner(board) {
  for (const [a, b, c] of LINES) {
    if (board[a] && board[a] === board[b] && board[a] === board[c]) return board[a];
  }
  return board.every((c) => c) ? "draw" : null;
}

function nextPlayer(board) {
  const x = board.filter((c) => c === "X").length;
  const o = board.filter((c) => c === "O").length;
  return x === o ? "X" : "O";
}

function score(board, me, depth) {
  const w = winner(board);
  if (w === me) return 10 - depth;
  if (w === "draw") return 0;
  if (w) return depth - 10;
  const turn = nextPlayer(board);
  let best = turn === me ? -Infinity : Infinity;
  for (let i = 0; i < 9; i++) {
    if (board[i]) continue;
    board[i] = turn;
    const s = score(board, me, depth + 1);
    board[i] = null;
    best = turn === me ? Math.max(best, s) : Math.min(best, s);
  }
  return best;
}

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
    if (s > best) { best = s; move = i; }
  }
  return move;
}

if (typeof module !== "undefined") module.exports = { winner, nextPlayer, bestMove };
