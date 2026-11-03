@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   FileButler 1.0.0-rc.2 - Windows EXE build
echo ========================================

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" was not found. Install Python 3.10+ from python.org.
  pause
  exit /b 1
)

if not exist .venv (
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :error
pip install -r requirements-build.txt
if errorlevel 1 goto :error

echo Running automated tests...
python -m unittest discover -s tests -v
if errorlevel 1 goto :error

python -m PyInstaller --noconfirm --clean FileButler.spec
if errorlevel 1 goto :error

echo.
echo Build complete: dist\FileButler.exe
echo Copy the EXE out of dist only after testing it on this PC.
pause
exit /b 0

:error
echo.
echo Build failed. Read the error above.
pause
exit /b 1
