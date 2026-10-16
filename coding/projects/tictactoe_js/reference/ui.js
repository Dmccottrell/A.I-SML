let board = Array(9).fill(null);
const cells = document.getElementById("board");
const status = document.getElementById("status");

function draw() {
  cells.innerHTML = "";
  board.forEach((v, i) => {
    const b = document.createElement("button");
    b.textContent = v || "";
    b.setAttribute("aria-label", "square " + (i + 1));
    b.onclick = () => play(i);
    cells.appendChild(b);
  });
  const w = winner(board);
  status.textContent = w === "draw" ? "It's a draw" : w ? w + " wins" : nextPlayer(board) + " to play";
}

function play(i) {
  if (board[i] || winner(board) || nextPlayer(board) !== "X") return;
  board[i] = "X";
  if (!winner(board)) board[bestMove(board)] = "O";
  draw();
}

document.getElementById("new").onclick = () => { board = Array(9).fill(null); draw(); };
draw();
