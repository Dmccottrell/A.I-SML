// The browser side of tic-tac-toe: draws the board as buttons, handles clicks, and lets the computer reply.
// It relies on game.js (loaded first by index.html) for winner(), nextPlayer() and bestMove().

// The board: 9 empty cells. Array(9).fill(null) makes a list of nine nulls.
let board = Array(9).fill(null);
// The two page elements we change: the box holding the nine buttons, and the status line.
const cells = document.getElementById("board");
const status = document.getElementById("status");

// Rebuild the whole board on the page from the `board` array and update the status text.
function draw() {
  // Clear the old buttons, then make one fresh button per cell.
  cells.innerHTML = "";
  board.forEach((v, i) => {
    const b = document.createElement("button");
    b.textContent = v || "";
    // aria-label is the name a screen reader says for the button (the visible text may be empty).
    b.setAttribute("aria-label", "square " + (i + 1));
    b.onclick = () => play(i);
    cells.appendChild(b);
  });
  // Status line: draw, a winner, or whose turn it is.
  const w = winner(board);
  status.textContent = w === "draw" ? "It's a draw" : w ? w + " wins" : nextPlayer(board) + " to play";
}

// The human (always X) clicked cell i. Ignore the click if the cell is taken, the game is over, or it is not X's turn.
// Then place X and, if the game goes on, let the computer place its O.
function play(i) {
  if (board[i] || winner(board) || nextPlayer(board) !== "X") return;
  board[i] = "X";
  if (!winner(board)) board[bestMove(board)] = "O";
  draw();
}

// "New game" button: reset to an empty board. Then draw the first board when the page loads.
document.getElementById("new").onclick = () => { board = Array(9).fill(null); draw(); };
draw();
