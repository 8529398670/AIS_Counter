@echo off
rem Open .czi and .tif images in napari, every channel as its own layer. The
rem Windows twin of scripts/view.sh.
rem
rem   scripts\view.bat IMAGE          that image; PageUp/PageDown (or [ and ])
rem                                   step through the others in its folder
rem   scripts\view.bat FOLDER         every .czi/.tif in it, first one shown
rem   scripts\view.bat A.czi B.tif    just those
rem
rem The same .venv as run.bat, plus app\requirements-view.txt (napari, Qt and
rem the .czi reader), installed here on first use; then `python -m app view`.
rem .venv itself comes from run.bat (`run.bat version` sets it up and returns).
rem As there, the requirements are installed again when they differ from the
rem copy saved after the last install.
setlocal

if not "%~1"=="" goto have_arguments
echo Usage: scripts\view.bat IMAGE ^| FOLDER ^| IMAGE...
echo   One layer per channel; PageUp/PageDown step through the folder.
exit /b 2
:have_arguments

rem Relative paths are relative to where this was run, not the project root:
rem %%~fA makes each one absolute before the cd below.
set "PATHS="
for %%A in (%*) do call set PATHS=%%PATHS%% "%%~fA"

cd /d "%~dp0.."
set "VENV=%CD%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "STAMP=%VENV%\.requirements-view.stamp"

call scripts\run.bat version
if errorlevel 1 exit /b 1

fc /b app\requirements-view.txt "%STAMP%" >nul 2>&1
if not errorlevel 1 goto requirements_ready
echo Installing app\requirements-view.txt (napari) into .venv (first time takes a minute)...
"%PYTHON%" -m pip install --quiet -r app\requirements-view.txt
if errorlevel 1 goto install_failed
copy /y app\requirements-view.txt "%STAMP%" >nul

:requirements_ready
"%PYTHON%" -m app view %PATHS%
exit /b %errorlevel%

:install_failed
echo.
echo ERROR: installing app\requirements-view.txt failed (above).
exit /b 1
