@echo off
rem ============================================================
rem  Kairos tests. Needs the stack running (run.bat).
rem    test.bat              pure-logic tests: backend (pytest) + frontend (vitest)
rem    test.bat evals        agent evaluations: classification + diagnosis
rem    test.bat evals all    ... plus end-to-end Jev RCA (minutes per incident)
rem    test.bat cold         cold-agent test: can a new agent use the platform via Kairos alone?
rem    test.bat cold legacy  ... the same agent with graph tools only, for comparison
rem  Evals call Databricks, TypeSafe and Azure OpenAI and spend LLM budget.
rem ============================================================
setlocal
cd /d "%~dp0"

if /i "%~1"=="evals" goto evals
if /i "%~1"=="cold" goto cold

echo === Backend (pytest) ===
docker compose exec -T api python -m pytest -q
set BACKEND=%errorlevel%

echo.
echo === Frontend (vitest) ===
pushd frontend
call npm test
set FRONTEND=%errorlevel%
popd

if not "%BACKEND%%FRONTEND%"=="00" (
    echo.
    echo [FAIL] backend=%BACKEND% frontend=%FRONTEND%
    exit /b 1
)
echo.
echo [OK] all pure-logic tests passed
exit /b 0

:evals
set SUITE=classification,diagnosis
if /i "%~2"=="all" set SUITE=all
docker compose exec -T api python -m kairos_kb.evals --suite %SUITE%
exit /b %errorlevel%

:cold
set TOOLSET=full
if /i "%~2"=="legacy" set TOOLSET=legacy
docker compose exec -T api python -m kairos_kb.evals.cold_agent --toolset %TOOLSET%
exit /b %errorlevel%
