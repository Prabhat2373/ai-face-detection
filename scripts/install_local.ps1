param(
  [string]$AppDir = (Get-Location).Path
)

$node = (Get-Command node).Source
$python = (Get-Command python).Source

Write-Host "Local deployment helper"
Write-Host "Application directory: $AppDir"
Write-Host ""
Write-Host "Suggested Windows service approach:"
Write-Host "Use NSSM or sc.exe to run:"
Write-Host "  $node $AppDir\dist\server.js"
Write-Host ""
Write-Host "Python recognizer can be started separately with:"
Write-Host "  $python $AppDir\python_recognizer\app.py"
