@echo off
cd /d "%~dp0"

rem Start Ollama if it isn't already running
tasklist /fi "imagename eq ollama.exe" | find /i "ollama.exe" >nul || start "Ollama" /min ollama serve
timeout /t 3 /nobreak >nul

rem Pull the model on first run
ollama list | find /i "qwen2.5:3b" >nul || ollama pull qwen2.5:3b

call .venv\Scripts\activate.bat

rem Open the browser once the server has had a moment to start
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:5000/"

python -m app.ui
pause
