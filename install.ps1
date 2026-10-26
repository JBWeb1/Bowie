# Install Bowers on Windows and add it to the Start menu and desktop.
# Run in PowerShell:  irm https://raw.githubusercontent.com/JBWeb1/Bowie/HEAD/install.ps1 | iex
# (or, from a copy of this repo:  powershell -ExecutionPolicy Bypass -File install.ps1)
param([string]$Source = "git+https://github.com/JBWeb1/Bowie", [switch]$NoLaunch)
$ErrorActionPreference = "Stop"

function Find-Python {
    foreach ($cmd in @("py -3", "python", "python3")) {
        $parts = $cmd.Split(" ")
        try {
            $v = & $parts[0] $parts[1..9] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($v -and [version]$v -ge [version]"3.10") { return $parts }
        } catch {}
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.10 or newer is needed. Installing it with winget..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = Find-Python
    if (-not $py) { throw "Python didn't install. Get it from https://www.python.org/downloads/ and run this again." }
}
if (-not (Get-Command git -ErrorAction SilentlyContinue) -and $Source -like "git+*") {
    Write-Host "Installing Git (needed to download Bowers)..." -ForegroundColor Yellow
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "Installing Bowers..." -ForegroundColor Cyan
& $py[0] $py[1..9] -m pip install --user --upgrade "docks[browser,labs] @ $Source"
& $py[0] $py[1..9] -m docks install-app

Write-Host ""
Write-Host "Bowers is installed. Open it from the Start menu or the desktop icon." -ForegroundColor Green
Write-Host "Add your API key once (it stays on this PC):" -ForegroundColor Green
Write-Host '  [Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "<your key>", "User")'
Write-Host "Optional: OPENAI_API_KEY (images, Codex, ChatGPT), LTX_API_KEY (Bowers Motion video), ELEVENLABS_API_KEY (Bowie's voice)."
if (-not $NoLaunch) { Start-Process -FilePath $py[0] -ArgumentList (@($py[1..9]) + @("-m", "docks", "app")) -WindowStyle Hidden }
