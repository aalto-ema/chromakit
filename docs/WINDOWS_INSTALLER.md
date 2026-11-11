# Windows installer

Open [Windows installer](https://github.com/aalto-ema/chromakit/actions/workflows/windows-installer.yml),
select a successful run, then download **ChromaKit-Windows-x64** under Artifacts.
GitHub requires a signed-in account for the download. Extract the ZIP and run
`ChromaKit-<version>-Windows-x64-Setup.exe`. This is an unsigned development build;
Windows may display an unknown-publisher prompt. Use only a trusted workflow artifact.

The installer targets x64 Windows 10 (1809 or newer) and Windows 11. It installs
under `%LOCALAPPDATA%\Programs\ChromaKit` by default, requires no administrator
rights, adds a Start menu shortcut, and offers an optional desktop shortcut.
Python and Qt are bundled. Uninstall from **Settings → Apps → Installed apps**.
Keep your project files outside the installation directory.

To verify the downloaded executable, compare the hash from
`Get-FileHash -Algorithm SHA256 .\ChromaKit-<version>-Windows-x64-Setup.exe`
(replace `<version>`) with the adjacent `.sha256` file. `build-info.txt` records
the source commit and build environment.

## Build and validation

The workflow runs on changes affecting the package on `main` and can be started
manually from its Actions page. It freezes ChromaKit with
[PyInstaller](https://pyinstaller.org/en/stable/) and wraps the resulting directory
with [Inno Setup](https://jrsoftware.org/isinfo.php). The Windows Server 2025 runner
installs, launches and uninstalls the result; the installed smoke test exercises
the Qt workspace, a synthetic trace, baseline correction, peak detection and PNG
export without relying on the build Python on PATH. This is automated smoke
coverage, not a manual desktop acceptance test on each supported Windows version.

For a local x64 Windows build, activate a Python 3.13 virtual environment, install
Inno Setup 6, and run from a clean checkout:

```powershell
python -m pip install . -r packaging/windows/requirements.txt
./packaging/windows/build.ps1
./packaging/windows/smoke-test.ps1
```

Use `-InnoCompiler 'C:\path\to\ISCC.exe'` with the build script if the compiler
is installed outside its default location. Outputs are in `dist/windows-installer`.
Runtime notices and source references are installed under `ThirdParty`.
Artifacts expire after 30 days. The workflow does not publish a GitHub Release
or sign binaries.
