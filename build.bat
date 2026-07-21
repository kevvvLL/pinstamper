@echo off
REM Packages PinStamper as a standalone Windows exe.
REM Usage: run build.bat from the repo root; output: dist\PinStamper.exe
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm PinStamp.spec
echo.
echo Done: dist\PinStamper.exe
