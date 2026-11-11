$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$setups = @(Get-ChildItem (Join-Path $root 'dist/windows-installer') -Filter '*-Setup.exe')
if ($setups.Count -ne 1) { throw 'Expected exactly one Windows setup executable.' }
$setup = $setups[0].FullName
$logs = Join-Path $root 'dist/windows-smoke'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$install = Join-Path ([IO.Path]::GetTempPath()) "ChromaKit Smoke $([guid]::NewGuid())"

function Invoke-CheckedProcess($Executable, $Arguments, $WorkingDirectory) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -PassThru
    try {
        if (-not $process.WaitForExit(120000)) {
            $process.Kill()
            throw "$Executable timed out."
        }
        if ($process.ExitCode -ne 0) { throw "$Executable exited with code $($process.ExitCode)." }
    } finally {
        $process.Dispose()
    }
}

$uninstaller = Join-Path $install 'unins000.exe'
$report = Join-Path $logs 'application.log'
Remove-Item $report -ErrorAction SilentlyContinue
try {
    Invoke-CheckedProcess $setup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
        ('/DIR="{0}"' -f $install), ('/LOG="{0}"' -f (Join-Path $logs 'install.log'))) $logs
    foreach ($file in @('ChromaKit.exe', 'unins000.exe', 'LICENSE', 'ThirdParty/README.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $install $file) -PathType Leaf)) {
            throw "Installer did not deploy $file."
        }
    }

    # Do not let build Python, Qt plugin paths or the checkout satisfy runtime imports.
    $runtimeEnvironment = @{
        PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        PYTHONPATH = $null
        PYTHONHOME = $null
        QT_PLUGIN_PATH = $null
        QT_QPA_PLATFORM_PLUGIN_PATH = $null
        QT_QPA_PLATFORM = 'windows'
    }
    $previous = @{}
    try {
        foreach ($name in $runtimeEnvironment.Keys) {
            $previous[$name] = [Environment]::GetEnvironmentVariable($name)
            [Environment]::SetEnvironmentVariable($name, $runtimeEnvironment[$name])
        }
        Invoke-CheckedProcess (Join-Path $install 'ChromaKit.exe') @(
            '--installer-smoke-test', ('"{0}"' -f $report)) $logs
    } finally {
        foreach ($name in $previous.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name])
        }
        if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report }
    }
    if (-not (Test-Path -LiteralPath $report) -or (Get-Content -Raw $report).Trim() -ne 'PASS') {
        throw 'The installed application did not report a successful smoke test.'
    }
} finally {
    if (Test-Path -LiteralPath $uninstaller) {
        Invoke-CheckedProcess $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            ('/LOG="{0}"' -f (Join-Path $logs 'uninstall.log'))) $logs
    }
}
if (Test-Path -LiteralPath (Join-Path $install 'ChromaKit.exe')) {
    throw 'Uninstall left ChromaKit.exe behind.'
}
