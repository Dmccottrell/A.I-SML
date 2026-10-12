@echo off
rem Gaming mode ON: Emvryx unloads its model (frees the graphics card and memory) within about 15 seconds, and chats say it is resting.
rem Double-click to switch on. gaming_off.cmd switches it off. (Same as Admin > PC > Gaming mode.)
echo Emvryx is paused for gaming. Delete this file (or run gaming_off.cmd) to turn it off.> "%~dp0..\.emvryx\gaming.flag"
echo Gaming mode is ON. The model will be unloaded in a few seconds.
timeout /t 3 >nul
