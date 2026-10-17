@echo off
rem ============================================================
rem  Kairos - one-click launcher
rem    Backend  : Docker (Postgres + API + pgAdmin)  -> http://localhost:8888/docs
rem    Frontend : Next.js dev server                 -> http://localhost:3000
rem  Usage: run.bat          start everything
rem         run.bat stop     stop the containers
rem ============================================================
setlocal
cd /d "%~dp0"

if /i "%~1"=="stop" (
    docker compose down
    echo Containers stopped. Close the "Kairos Frontend" window to stop the UI.
    exit /b 0
)

rem ---- 1. Prerequisites --------------------------------------
where docker >nul 2>&1 || (echo [ERROR] Docker is not installed. & pause & exit /b 1)
where npm    >nul 2>&1 || (echo [ERROR] Node.js/npm is not installed. & pause & exit /b 1)

if not exist ".env" (
    echo [INFO] No .env found - copying .env.example. Fill in your secrets, then re-run.
    copy .env.example .env >nul
    notepad .env
    pause
    exit /b 1
)

rem ---- 2. Make sure Docker Desktop is running ----------------
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
echo [INFO] Starting Docker Desktop...
start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a tries=0
:wait_docker
timeout /t 3 /nobreak >nul
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
set /a tries+=1
if %tries% geq 60 (echo [ERROR] Docker did not start within 3 minutes. & pause & exit /b 1)
goto wait_docker
:docker_ready
echo [OK] Docker is running.

rem ---- 3. Backend containers ---------------------------------
echo [INFO] Building and starting backend containers...
docker compose up -d --build
if errorlevel 1 (echo [ERROR] docker compose failed. & pause & exit /b 1)

echo [INFO] Waiting for the API to become healthy...
set /a tries=0
:wait_api
timeout /t 2 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://localhost:8888/health | findstr "200" >nul
if not errorlevel 1 goto api_ready
set /a tries+=1
if %tries% geq 90 (
    echo [WARN] API not healthy after 3 minutes. Check: docker compose logs api
    goto start_frontend
)
goto wait_api
:api_ready
echo [OK] API is up.

rem ---- 4. Frontend -------------------------------------------
:start_frontend
if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    pushd frontend
    call npm install
    popd
)

echo [INFO] Starting frontend in a new window...
start "Kairos Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

rem Give Next.js a moment, then open the browser.
timeout /t 8 /nobreak >nul
start "" http://localhost:3000

echo.
echo ============================================================
echo   Frontend : http://localhost:3000
echo   API docs : http://localhost:8888/docs
echo   pgAdmin  : http://localhost:5051  (admin@kairos.dev / admin)
echo   Stop     : run.bat stop
echo ============================================================
endlocal
