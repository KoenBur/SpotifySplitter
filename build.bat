@echo off
rem Builds dist\SpotifySplitter.exe, a single file that runs without Python installed.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -m venv .venv 2>nul || python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt pyinstaller || goto failed

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name SpotifySplitter ^
    --icon "%CD%\assets\icon.ico" ^
    --version-file "%CD%\assets\version.txt" ^
    --add-data "%CD%\templates;templates" ^
    --add-data "%CD%\static;static" ^
    --specpath build ^
    app.py || goto failed

echo.
echo Done: dist\SpotifySplitter.exe
pause
exit /b 0

:failed
echo.
echo The build failed; see the messages above.
pause
exit /b 1
