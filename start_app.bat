@echo off
setlocal

set "REPO_ROOT=%~dp0"
set "FRONTEND_DIR=%REPO_ROOT%frontend"
set "VENV_PYTHON=%REPO_ROOT%venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
  echo Virtual environment Python was not found at "%VENV_PYTHON%"
  exit /b 1
)

pushd "%FRONTEND_DIR%" || exit /b 1

if not exist "node_modules" (
  call npm install
  if errorlevel 1 (
    popd
    exit /b 1
  )
)

call npm run build
if errorlevel 1 (
  popd
  exit /b 1
)

popd

"%VENV_PYTHON%" "%REPO_ROOT%app.py"
