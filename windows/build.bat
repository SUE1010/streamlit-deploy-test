@echo off
REM Run this from the "windows" folder on a Windows PC with Python installed.
setlocal

cd /d "%~dp0"

echo [1/3] Installing app + build dependencies...
py -m pip install -r ..\requirements.txt -r requirements-build.txt
if errorlevel 1 goto :error

echo [2/3] Building JejuChatbot.exe with PyInstaller...
py -m PyInstaller --noconfirm --onefile --name JejuChatbot ^
    --collect-all streamlit ^
    --collect-all openai ^
    --add-data "..\streamlit-chatbot.py;." ^
    --hidden-import streamlit.web.cli ^
    launcher.py
if errorlevel 1 goto :error

echo [3/3] Done. The executable is at windows\dist\JejuChatbot.exe
goto :eof

:error
echo Build failed. See the messages above.
exit /b 1
