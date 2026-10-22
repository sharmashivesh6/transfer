@echo off
rem Run once on any Windows PC with Python installed. Output: dist\Transfer.exe (runs on PCs without Python).
cd /d "%~dp0"
py -m pip install --upgrade pyinstaller || goto :err
py -m PyInstaller --onefile --name Transfer transfer.py || goto :err
echo.
echo Done: %~dp0dist\Transfer.exe
pause
exit /b 0
:err
echo Build failed. Is Python installed? https://www.python.org/downloads/
pause
exit /b 1
