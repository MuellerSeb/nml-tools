@echo off
cd /d "%~dp0"
nml-tools gui
if errorlevel 1 pause
