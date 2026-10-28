@echo off
title Rebuilt render server
cd /d "%~dp0"
call find_blender.bat
if not defined BLENDER (
  echo Blender was not found. Install Blender 4.2 or newer from https://www.blender.org/download/
  echo or set the BLENDER variable to the full path of blender.exe, then run this again.
  pause & exit /b 1
)
echo Using %BLENDER%
"%BLENDER%" -b --factory-startup -P "%~dp0render_server.py" -- %*
echo.
echo Finished. Images are in the outputs folder.
pause
