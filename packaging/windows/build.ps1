param([string]$InnoCompiler)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $root
try {
    if (-not $InnoCompiler) {
        $InnoCompiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
    }
    $InnoCompiler = (Resolve-Path -LiteralPath $InnoCompiler).Path
    $version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') {
        throw 'Expected a numeric ChromaKit version in pyproject.toml.'
    }
    python -c "import platform, struct, sys; assert sys.platform == 'win32' and platform.machine() == 'AMD64' and struct.calcsize('P') == 8"
    if ($LASTEXITCODE -ne 0) { throw 'The build requires x64 Windows Python.' }

    $output = Join-Path $root 'dist/windows-installer'
    $bundle = Join-Path $root 'dist/windows-bundle/ChromaKit'
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    $setup = Join-Path $output "ChromaKit-$version-Windows-x64-Setup.exe"
    # PyInstaller resolves data paths from the generated spec, not this checkout.
    $sample = Join-Path $root 'examples/synthetic_uv.csv'
    $freezeArgs = @('--noconfirm', '--clean', '--onedir', '--windowed', '--noupx',
        '--name', 'ChromaKit', '--distpath', 'dist/windows-bundle', '--workpath', 'build/windows',
        '--specpath', 'build/windows', '--add-data', "${sample}:examples",
        '--hidden-import', 'matplotlib.backends.backend_agg', 'packaging/windows/launcher.py')
    python -m PyInstaller @freezeArgs
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    python packaging/windows/notices.py $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare runtime notices.' }

    & $InnoCompiler "/DAppVersion=$version" "/DBundleDir=$bundle" "/O$output" packaging/windows/ChromaKit.iss
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $setup)) {
        throw 'Inno Setup failed.'
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $setup).Hash.ToLowerInvariant()
    "$hash  $(Split-Path -Leaf $setup)" | Set-Content -Encoding ascii "$setup.sha256"

    $commit = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Could not determine the source commit.' }
    @("ChromaKit $version", "Commit: $commit", "Architecture: Windows x64",
      "Python: $(python --version)", "Inno Setup: $((Get-Item $InnoCompiler).VersionInfo.ProductVersion)",
      "Runner image: $env:ImageVersion") | Set-Content -Encoding utf8 "$output/build-info.txt"
    python -m pip list --format=freeze | Add-Content -Encoding utf8 "$output/build-info.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Could not record build dependencies.' }
    if ($env:GITHUB_STEP_SUMMARY) {
        @("### Windows x64 installer", "", (Split-Path -Leaf $setup),
          "", "SHA-256: $hash") | Add-Content -Path $env:GITHUB_STEP_SUMMARY
    }
} finally {
    Pop-Location
}
