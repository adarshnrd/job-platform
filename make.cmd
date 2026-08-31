@echo off
if exist "%CD%\scripts\runner.js" (
    node "%CD%\scripts\runner.js" %*
) else (
    echo Job Platform Makefile Runner
    echo Usage: make [start^|api^|web^|install^|stop^|help]
)
