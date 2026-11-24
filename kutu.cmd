@echo off
rem kutu: Windows sarmalayici. Python'u py -3, sonra python, sonra tam yol ile bulur.
set "KUTU_PY=%~dp0kutu.py"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%KUTU_PY%" %*
  exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%KUTU_PY%" %*
  exit /b
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%KUTU_PY%" %*
  exit /b
)
echo kutu: Python 3 bulunamadi 1>&2
exit /b 9009
