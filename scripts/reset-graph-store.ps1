param(
    [string]$StoreDir = "",
    [switch]$AllTurtleFiles
)

if ([string]::IsNullOrWhiteSpace($StoreDir)) {
    $StoreDir = $env:RDFLIB_STORE_DIR
}
if ([string]::IsNullOrWhiteSpace($StoreDir)) {
    $StoreDir = "data/graph-store"
}

$storePath = Join-Path $PSScriptRoot "..\$StoreDir"
$storePath = (Resolve-Path (New-Item -ItemType Directory -Force -Path $storePath)).Path

if ($AllTurtleFiles) {
    Get-ChildItem -Path $storePath -Filter "*.ttl" -File | Remove-Item -Force
    Write-Host "Cleared all .ttl files in $storePath"
    exit 0
}

$knownFiles = @(
    "raw.ttl",
    "asserted.ttl",
    "inferred.ttl",
    "validation-reports.ttl"
)

foreach ($name in $knownFiles) {
    $target = Join-Path $storePath $name
    if (Test-Path $target) {
        Remove-Item -Path $target -Force
    }
}

Write-Host "Cleared known graph files in $storePath"
