@echo off
rem Gaming mode OFF: chats work again; the next message loads the model (the first reply is slow while it loads).
del "%~dp0..\.emvryx\gaming.flag" 2>nul
echo Gaming mode is OFF.
timeout /t 3 >nul
