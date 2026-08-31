@echo off
:: Creates a desktop shortcut for the Nasdaq Mood Dashboard
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"
pause
