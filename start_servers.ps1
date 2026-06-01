Start-Process -NoNewWindow -FilePath "C:\Users\User\Desktop\Ridoy\vs code\REAL_MONEY\backend\venv\Scripts\python.exe" -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8000"
Start-Process -NoNewWindow -FilePath "npx.cmd" -ArgumentList "next dev -p 3000"
