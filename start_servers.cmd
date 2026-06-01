@echo off
title REAL_MONEY Servers
echo Starting Backend...
start "REAL_MONEY-Backend" /B "C:\Users\User\Desktop\Ridoy\vs code\REAL_MONEY\backend\venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
echo Starting Frontend...
start "REAL_MONEY-Frontend" /B "npx.cmd" next dev -p 3000
echo Both servers started.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
pause
