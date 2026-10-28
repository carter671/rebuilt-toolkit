@echo off
rem Keeps the render server running: new job files dropped into jobs\ are rendered automatically.
call "%~dp0RENDER.bat" --watch
