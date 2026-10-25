@echo off
title Kemono and Coomer Downloader
cd /d "%~dp0"
chcp 65001 >nul
py -3 main.py
if errorlevel 1 (
    echo.
    pause
)
