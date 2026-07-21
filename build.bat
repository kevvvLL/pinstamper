@echo off
REM Packages PinStamp as a standalone Windows exe.
REM Usage: run build.bat from the repo root; output: dist\PinStamp.exe
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm PinStamp.spec
echo.
echo Done: dist\PinStamp.exe
