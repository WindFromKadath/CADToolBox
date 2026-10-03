# Scope UV storage and backend caches to this project for every command.
$cadProjectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $cadProjectRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $cadProjectRoot '.cache\python'
$env:XDG_CACHE_HOME = Join-Path $cadProjectRoot '.cache'
$env:MPLCONFIGDIR = Join-Path $cadProjectRoot '.cache\matplotlib'
Push-Location -LiteralPath $cadProjectRoot
try {
    & uv @args
    $cadCommandExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $cadCommandExit
