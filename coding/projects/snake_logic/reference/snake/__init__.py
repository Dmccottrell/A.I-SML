# Package entry for the snake reference solution ("snake_logic" exercise). It re-exports render() and Game so users
# can write `from snake import Game, render`. The noqa notes tell the linter these imports are meant to be "unused" here.
from snake.board import render  # noqa: F401
from snake.game import Game  # noqa: F401
