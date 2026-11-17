@echo off
chcp 65001 >nul
rem 用便携版 DB Browser 打开本项目数据库
start "" "%~dp0tools\DBBrowser\DB Browser for SQLite.exe" "%~dp0instance\orchard.db"
