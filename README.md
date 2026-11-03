# FileButler 1.0.0-rc.2

A local-first Windows file organizer built with Python and PySide6.

## Release status

This is a **1.0.0-rc.2 build candidate**. The source and automated checks are prepared, but the packaged Windows executable must still be built and smoke-tested on Windows before claiming a stable final release.

## Features

- Recursive or top-level folder scanning in a background thread.
- Progress feedback and scan cancellation.
- Live search by filename, extension, category, and parent path.
- Duplicate Manager with cancellable background SHA-256 hashing (review only; no automatic deletion).
- Drag & Drop a folder or file into the app to scan its containing folder.
- Sorting preview and explicit confirmation before moving files.
- Persistent Undo journal with checks against overwriting and changed file contents.
- Atomic writes for configuration and operation history.
- File symlinks are excluded from scans to avoid accidentally moving external targets.
- Sorting plans ignore files outside the selected root.
- Custom extension-to-folder sorting rules.
- JSON scan report export.
- Remembers the last folder, recursive-scan preference, and window size locally.\n- Local processing; no account, cloud upload, or telemetry.

## Run from source (Windows)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

If PowerShell activation is blocked:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Build a standalone Windows EXE

The EXE must be built on Windows (PyInstaller does not reliably cross-compile Windows executables from Linux/macOS).

1. Install Python 3.10+ on Windows and enable the Python Launcher.
2. Open the project folder in File Explorer.
3. Double-click `build_windows.bat`.
4. Wait for PyInstaller to finish.
5. The executable will be created at `dist\FileButler.exe`.

The build script creates a local virtual environment and installs dependencies from `requirements-build.txt`. The output is a one-file, windowed executable; first launch may take longer while PyInstaller unpacks its runtime.

For a distributable release, test `dist\FileButler.exe` on a clean Windows account or Windows VM. Windows SmartScreen may show a warning for unsigned builds. Do not distribute a build until it has been tested on the target Windows versions.

## Build the Windows EXE with GitHub Actions

The repository includes a workflow at `.github/workflows/build-windows.yml`.
It runs on pushes and pull requests targeting `main` or `master`, and can also
be started manually from the **Actions** tab.

The workflow:

1. Runs on `windows-latest` with Python 3.11.
2. Installs the dependencies listed in `requirements-build.txt`.
3. Runs the existing unit tests with `unittest`.
4. Builds the executable using the checked-in `FileButler.spec`.
5. Verifies that `dist/FileButler.exe` exists and is not empty.
6. Uploads it as the `FileButler-windows-x64` workflow artifact for 14 days.

To use it:

1. Put the project files in a GitHub repository and ensure `FileButler.spec`
   is committed. The `.gitignore` explicitly allows this file.
2. Push the `main` or `master` branch (or open a pull request targeting one
   of those branches).
3. On GitHub, open **Actions** and select **Build Windows EXE**.
4. Open the completed workflow run, find **Artifacts**, and download
   `FileButler-windows-x64`.
5. Extract the downloaded ZIP; it contains `FileButler.exe`.

You can also start a build manually using **Actions → Build Windows EXE →
Run workflow**. Manual runs and ordinary branch builds create an artifact only.

To publish a GitHub Release, push a version tag such as `v1.0.0-rc.1`. The
workflow waits for the test job, builds the Windows executable, then attaches
`FileButler.exe` to the GitHub Release. Never tag the final `v1.0.0` until the
release candidate has passed a clean-Windows smoke test. The executable is
unsigned and is not an installer; Windows SmartScreen may warn users.
A successful local test run does not prove that the Windows packaging step
works; the executable is confirmed only after a successful GitHub Actions run.

## Release checklist

Before declaring `1.0.0` stable:

- [ ] All CI jobs pass on the release commit.
- [ ] Build `FileButler.exe` from the tagged commit on GitHub Actions.
- [ ] Launch it on a clean supported Windows installation without Python.
- [ ] Test scan, preview, sorting, undo, custom rules, duplicate review, and report export.
- [ ] Test denied permissions, duplicate filenames, interrupted operations, and large folders.
- [ ] Verify settings/history persist and no files are uploaded or deleted.
- [ ] Publish final `v1.0.0` only after the above checks pass.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## Data and safety

- Files are processed locally.
- FileButler does not delete files.
- Sorting requires preview and explicit confirmation.
- Undo refuses to overwrite an occupied original path or restore a file whose SHA-256 no longer matches.
- Rules and operation history are stored in the current user's application configuration directory.

## Known limitations

- Large duplicate scans still consume disk I/O and CPU, but hashing runs in a worker thread to keep the interface responsive.
- The scan progress indicator reports the number of files encountered, not a percentage, because the total is not known in advance.
- Drag & Drop uses the first valid local file or folder in the dropped items.
- The one-file EXE build is configured but must be produced and tested on Windows.
- No code-signing certificate is included.

## License

MIT. See [LICENSE](LICENSE).
