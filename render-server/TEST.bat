@echo off
rem 30-second check that Blender, the graphics card and the model all work. Output: outputs\waterloo-d2\00-smoke-test
cd /d "%~dp0"
echo {"project": "waterloo-d2", "preset": "smoke-test"} > jobs\00-smoke-test.json
call "%~dp0RENDER.bat"
