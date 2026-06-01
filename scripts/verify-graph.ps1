param(
    [string]$Backend = "",
    [string]$Dataset = "kg",
    [string]$FusekiBaseUrl = "http://localhost:3030",
    [string]$Username = "admin",
    [string]$Password = "admin"
)

if ([string]::IsNullOrWhiteSpace($Backend)) {
    $Backend = $env:GRAPH_BACKEND
}
if ([string]::IsNullOrWhiteSpace($Backend)) {
    $Backend = "rdflib"
}
$Backend = $Backend.ToLowerInvariant()

$graphs = @(
    "urn:graph:raw",
    "urn:graph:asserted",
    "urn:graph:inferred",
    "urn:graph:validation-reports"
)

$pair = "$Username`:$Password"
$basicToken = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{
    Authorization = "Basic $basicToken"
    Accept = "application/sparql-results+json"
}

$rows = @()
if ($Backend -eq "fuseki") {
    foreach ($graph in $graphs) {
        $query = "SELECT (COUNT(*) AS ?count) WHERE { GRAPH <$graph> { ?s ?p ?o } }"
        $encodedQuery = [System.Uri]::EscapeDataString($query)
        $url = "$FusekiBaseUrl/$Dataset/sparql?query=$encodedQuery"

        try {
            $result = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
            $count = [int]$result.results.bindings[0].count.value
        }
        catch {
            $count = -1
        }

        $rows += [PSCustomObject]@{
            Graph = $graph
            TripleCount = $count
        }
    }
}
elseif ($Backend -eq "rdflib") {
    $storeDir = Join-Path $PSScriptRoot "..\data\graph-store"
    $storeDir = (Resolve-Path (New-Item -ItemType Directory -Force -Path $storeDir)).Path

    $pythonCmd = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
    if (-not (Test-Path $pythonCmd)) {
        $pythonCmd = "py"
    }

    foreach ($graph in $graphs) {
        $fileName = "raw.ttl"
        if ($graph -eq "urn:graph:asserted") { $fileName = "asserted.ttl" }
        elseif ($graph -eq "urn:graph:inferred") { $fileName = "inferred.ttl" }
        elseif ($graph -eq "urn:graph:validation-reports") { $fileName = "validation-reports.ttl" }

        $graphPath = Join-Path $storeDir $fileName
        if (-not (Test-Path $graphPath)) {
            $count = 0
        }
        else {
            try {
                $count = & $pythonCmd -c "import rdflib,sys; g=rdflib.Graph(); g.parse(sys.argv[1]); print(len(g))" $graphPath
                $count = [int]$count
            }
            catch {
                $count = -1
            }
        }

        $rows += [PSCustomObject]@{
            Graph = $graph
            TripleCount = $count
        }
    }
}
else {
    throw "Unsupported backend '$Backend'. Use 'rdflib' (default) or 'fuseki'."
}

$rows | Format-Table -AutoSize
