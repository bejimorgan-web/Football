param(
  [string]$PythonVersion = "3.11.9",
  [string]$Architecture = "amd64"
)

$ErrorActionPreference = "Stop"

$desktopDir = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $desktopDir
$backendRequirements = Join-Path $projectRoot "backend\requirements.txt"
$runtimeRoot = Join-Path $desktopDir "runtime\python\windows"
$downloadDir = Join-Path $desktopDir ".downloads"
$pythonZip = Join-Path $downloadDir "python-$PythonVersion-embed-$Architecture.zip"
$pythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-$Architecture.zip"
$getPipPath = Join-Path $downloadDir "get-pip.py"

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null

Write-Host "Downloading portable Python from $pythonUrl"
Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonZip

Write-Host "Extracting runtime into $runtimeRoot"
Expand-Archive -Path $pythonZip -DestinationPath $runtimeRoot -Force

$pthFile = Get-ChildItem -Path $runtimeRoot -Filter "*._pth" | Select-Object -First 1
if ($pthFile) {
  $lines = Get-Content $pthFile.FullName
  if (-not ($lines -contains "import site")) {
    $updated = foreach ($line in $lines) {
      if ($line -eq "#import site") {
        "import site"
      } else {
        $line
      }
    }
    if (-not ($updated -contains "import site")) {
      $updated += "import site"
    }
    Set-Content -Path $pthFile.FullName -Value $updated -Encoding UTF8
  }
}

Write-Host "Bootstrapping pip"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath
& (Join-Path $runtimeRoot "python.exe") $getPipPath

Write-Host "Installing backend requirements"
& (Join-Path $runtimeRoot "python.exe") -m pip install --upgrade pip
& (Join-Path $runtimeRoot "python.exe") -m pip install -r $backendRequirements

Write-Host "Portable Python runtime is ready in $runtimeRoot"
