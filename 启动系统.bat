@echo off
chcp 65001 >nul
title 陈皮柑果园智慧管理系统
cd /d "%~dp0"
echo 正在启动智慧果园系统，请稍候...
echo.
if exist "D:\Anaconda\envs\Deep\python.exe" (
  "D:\Anaconda\envs\Deep\python.exe" run.py
) else (
  python run.py
)
echo.
echo 服务已停止。按任意键关闭窗口...
pause >nul
