param(
    [string]$Python = "",
    [switch]$UseVenv,
    [string]$VenvPath = ".venv",
    [switch]$VerifyOnly,
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

function Set-PythonCommand {
    param(
        [string]$Exe,
        [string[]]$PrefixArgs = @()
    )
    $script:PythonExe = $Exe
    $script:PythonPrefixArgs = $PrefixArgs
}

function Resolve-BasePython {
    if ($Python) {
        return @{ Exe = $Python; PrefixArgs = @() }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @{ Exe = $pythonCmd.Source; PrefixArgs = @() }
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @{ Exe = $pyCmd.Source; PrefixArgs = @("-3") }
    }

    throw "Python was not found. Install Python 3.10+ and retry."
}

function Invoke-Python {
    param([string[]]$Arguments)
    & $script:PythonExe @script:PythonPrefixArgs @Arguments
}

function Test-PythonVersion {
    Invoke-Python @("-c", "import sys; print(f'Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} at {sys.executable}')")
}

if (-not (Test-Path "requirements.txt")) {
    throw "requirements.txt not found in $PSScriptRoot"
}

$basePython = Resolve-BasePython
Set-PythonCommand -Exe $basePython.Exe -PrefixArgs $basePython.PrefixArgs

if ($UseVenv) {
    if (-not (Test-Path $VenvPath)) {
        Write-Host "[install] creating virtual environment: $VenvPath"
        Invoke-Python @("-m", "venv", $VenvPath)
    }

    $venvPython = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "Virtual environment Python not found: $venvPython"
    }

    Set-PythonCommand -Exe (Resolve-Path $venvPython).Path -PrefixArgs @()
}

Write-Host "[install] using Python:"
Test-PythonVersion

if (-not $VerifyOnly) {
    Write-Host "[install] upgrading pip, setuptools, wheel"
    Invoke-Python @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")

    Write-Host "[install] installing project dependencies from requirements.txt"
    Invoke-Python @("-m", "pip", "install", "-r", "requirements.txt")
}

if (-not $SkipVerify) {
    Write-Host "[install] verifying imports"
    $verifyScript = @'
import importlib
import sys

checks = [
    ("pywin32 / win32gui", "win32gui"),
    ("Pillow", "PIL"),
    ("OpenCV", "cv2"),
    ("NumPy", "numpy"),
    ("OpenAI", "openai"),
    ("psutil", "psutil"),
    ("python-dotenv", "dotenv"),
    ("RapidOCR", "rapidocr"),
]

failed = []
for label, module_name in checks:
    try:
        module = importlib.import_module(module_name)
        version = getattr(module, "__version__", "")
        suffix = f" {version}" if version else ""
        print(f"[ok] {label}{suffix}")
    except Exception as exc:
        failed.append((label, module_name, repr(exc)))
        print(f"[fail] {label}: {exc}")

if failed:
    print("")
    print("Missing or broken dependencies:")
    for label, module_name, exc in failed:
        print(f"- {label} ({module_name}): {exc}")
    sys.exit(1)

print("[ok] dependency verification passed")
'@
    $verifyScript | & $script:PythonExe @script:PythonPrefixArgs -
}

Write-Host ""
Write-Host "[install] done"
if ($UseVenv) {
    Write-Host "[install] activate with: .\$VenvPath\Scripts\Activate.ps1"
}
