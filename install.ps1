<#
.SYNOPSIS
    Download and install RideController on Windows, without git.

.DESCRIPTION
    Finds a usable Python, downloads this repository as a zip, unpacks it and
    installs it with pip. Ends by running `ridecontroller doctor`.

    Nothing here needs administrator rights. ViGEmBus, if it is missing, asks
    for them itself the first time the virtual pad is created.

.PARAMETER Path
    Where to put the checkout. Defaults to %USERPROFILE%\RideController.

.PARAMETER Force
    Replace an existing RideController install at -Path. Refuses to touch a
    directory that does not look like one.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Path D:\Tools\RideController
#>
[CmdletBinding()]
param(
    [string] $Path = (Join-Path $HOME 'RideController'),
    [switch] $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ZipUrl = 'https://github.com/DBYoder/RideController/archive/HEAD.zip'
$MinPython = [version]'3.10'

# Windows PowerShell 5.1 can still default to TLS 1.0, which github.com refuses.
[Net.ServicePointManager]::SecurityProtocol =
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Write-Step { param([string] $Message) Write-Host "`n$Message" -ForegroundColor Cyan }
function Write-Ok   { param([string] $Message) Write-Host "  [ok]   $Message" }
function Write-Warn { param([string] $Message) Write-Host "  [warn] $Message" -ForegroundColor Yellow }
function Write-Fail { param([string] $Message) Write-Host "  [FAIL] $Message" -ForegroundColor Red }

# Returns a descriptor for the first Python >= $MinPython on PATH, or $null.
# `py -3` is tried first: it is the launcher Windows installs, and it keeps
# working when python.exe itself is not on PATH.
function Find-Python {
    $candidates = @(
        [pscustomobject] @{ Exe = 'py';      Prefix = @('-3') },
        [pscustomobject] @{ Exe = 'python';  Prefix = @() },
        [pscustomobject] @{ Exe = 'python3'; Prefix = @() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }

        $probe = $candidate.Prefix + @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')
        try {
            $output = & $candidate.Exe @probe 2>$null
        } catch {
            continue
        }

        # A bare `python` on a clean Windows box is often the Microsoft Store
        # stub, which prints nothing and exits 9009.
        if ($LASTEXITCODE -ne 0 -or -not $output) { continue }

        $reported = ($output | Select-Object -First 1).ToString().Trim()
        if ($reported -notmatch '^\d+\.\d+$') { continue }

        if ([version] $reported -lt $MinPython) {
            Write-Warn "$($candidate.Exe) is Python $reported - too old, need $MinPython or newer"
            continue
        }

        return [pscustomobject] @{
            Exe     = $candidate.Exe
            Prefix  = $candidate.Prefix
            Version = $reported
            Display = (@($candidate.Exe) + $candidate.Prefix) -join ' '
        }
    }

    return $null
}

function Invoke-Python {
    param(
        [Parameter(Mandatory)] $Python,
        [Parameter(Mandatory)] [string[]] $Arguments
    )

    $all = $Python.Prefix + $Arguments
    & $Python.Exe @all
    if ($LASTEXITCODE -ne 0) {
        throw "$($Python.Display) $($Arguments -join ' ') exited with $LASTEXITCODE"
    }
}

# Only ever delete a directory we are confident we created.
function Test-RideControllerCheckout {
    param([Parameter(Mandatory)] [string] $Directory)

    $pyproject = Join-Path $Directory 'pyproject.toml'
    if (-not (Test-Path -LiteralPath $pyproject)) { return $false }
    return (Select-String -LiteralPath $pyproject -Pattern '^name\s*=\s*"ridecontroller"' -Quiet)
}

Write-Host 'RideController installer'
Write-Host '========================'

Write-Step 'Looking for Python...'
$python = Find-Python
if (-not $python) {
    Write-Fail 'no Python 3.10 or newer found on PATH'
    Write-Host ''
    Write-Host '  Install it, then run this script again:'
    Write-Host ''
    Write-Host '      winget install --id Python.Python.3.12 --source winget'
    Write-Host ''
    Write-Host '  or download it from https://www.python.org/downloads/windows/'
    Write-Host '  and tick "Add python.exe to PATH" in the installer.'
    Write-Host ''
    Write-Host '  Close and reopen PowerShell afterwards so PATH is picked up.'
    exit 1
}
Write-Ok "Python $($python.Version) via '$($python.Display)'"

Write-Step "Checking the target directory..."
if (Test-Path -LiteralPath $Path) {
    if (-not $Force) {
        Write-Fail "$Path already exists"
        Write-Host ''
        Write-Host '  Re-run with -Force to replace it, or choose another location:'
        Write-Host ''
        Write-Host "      .\install.ps1 -Path D:\Tools\RideController"
        exit 1
    }

    if (-not (Test-RideControllerCheckout -Directory $Path)) {
        Write-Fail "$Path exists but does not look like a RideController install"
        Write-Host '  Refusing to delete it. Move it aside, or pass a different -Path.'
        exit 1
    }

    Write-Warn "replacing the existing install at $Path"
    Remove-Item -LiteralPath $Path -Recurse -Force
}
Write-Ok $Path

$staging = Join-Path ([IO.Path]::GetTempPath()) ('ridecontroller-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging | Out-Null

try {
    Write-Step 'Downloading...'
    $zip = Join-Path $staging 'source.zip'
    # Invoke-WebRequest is far quicker without its progress bar.
    $previousProgress = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $ZipUrl -OutFile $zip -UseBasicParsing
    } finally {
        $ProgressPreference = $previousProgress
    }
    Write-Ok ('{0:N0} KB from github.com' -f ((Get-Item -LiteralPath $zip).Length / 1KB))

    Write-Step 'Unpacking...'
    $unpacked = Join-Path $staging 'unpacked'
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked -Force

    # GitHub wraps the tree in one directory named after the commit.
    $root = Get-ChildItem -LiteralPath $unpacked -Directory | Select-Object -First 1
    if (-not $root) { throw 'the downloaded archive was empty' }

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Move-Item -LiteralPath $root.FullName -Destination $Path
    Write-Ok $Path

    Write-Step 'Installing (this pulls in bleak and vgamepad)...'
    Invoke-Python -Python $python -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-e', $Path)
    Write-Ok 'installed'
} catch {
    Write-Host ''
    Write-Fail $_.Exception.Message
    exit 1
} finally {
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Step 'Checking the install...'
Write-Host ''
# `py -m ridecontroller` works whether or not pip's Scripts directory is on PATH.
& $python.Exe @($python.Prefix + @('-m', 'ridecontroller', 'doctor'))

Write-Host ''
Write-Host 'Done. To use it:' -ForegroundColor Cyan
Write-Host ''
Write-Host '    1. Wake the Zwift Ride, and close Zwift and the Companion app.'
Write-Host "    2. $($python.Display) -m ridecontroller scan"
Write-Host "    3. $($python.Display) -m ridecontroller run"
Write-Host ''
Write-Host '  Start step 3 before launching Steam, and leave the window open.'
Write-Host ''
Write-Host "  If 'ridecontroller' alone is not a recognised command, pip's Scripts"
Write-Host "  directory is not on PATH - keep using '$($python.Display) -m ridecontroller'."
Write-Host ''
