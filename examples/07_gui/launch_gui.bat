@echo off
cd /d "%~dp0"
if not exist out mkdir out
nml-tools gui -i ./ -o ./out
if errorlevel 1 pause
