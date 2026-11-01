@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 goto fail
py -m PyInstaller --noconfirm --onefile --windowed --name MediaRescueV2 media_rescue_v2.py
if errorlevel 1 goto fail
echo Built: dist\MediaRescueV2.exe
pause
exit /b 0
:fail
echo Build failed. Install Python 3.11+ from python.org, enable the Python launcher, and try again.
pause
exit /b 1
