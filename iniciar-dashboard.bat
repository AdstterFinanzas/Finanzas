@echo off
title Dashboard Herramientas Financieras - Adstter
color 1F
echo.
echo  ============================================
echo   Dashboard Herramientas Financieras Adstter
echo  ============================================
echo.
echo  Iniciando servidor en http://localhost:8787
echo  Presiona Ctrl+C en esta ventana para detener
echo.

cd /d "%~dp0"

:: Abrir el navegador despues de 1 segundo
start "" cmd /c "timeout /t 1 /nobreak >nul && start http://localhost:8787"

:: Iniciar servidor Python
python dashboard-server.py

pause
