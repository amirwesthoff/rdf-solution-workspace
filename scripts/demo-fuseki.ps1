param(
    [string]$InputTextPath = "",
    [switch]$ResetFirst,
    [switch]$LaunchApi,
    [string]$FusekiBaseUrl = "http://localhost:3030",
    [string]$Dataset = "kg",
    [string]$Username = "admin",
    [string]$Password = "admin",
    [int]$StartupTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

$repoRoot = Join-Path $PSScriptRoot ".."
Push-Location $repoRoot

function Wait-FusekiReady {
    param(
        [string]$BaseUrl,
        [string]$User,
        [string]$Pass,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $pair = "$User`:$Pass"
    $basicToken = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
    $headers = @{ Authorization = "Basic $basicToken" }

    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri "$BaseUrl/`$/datasets" -Headers $headers -Method Get | Out-Null
            return
        }
        catch {
            Start-Sleep -Milliseconds 750
        }
    }

    throw "Fuseki did not become ready within $TimeoutSeconds second(s)."
}

try {
    $pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) {
        throw "Python executable not found at .venv\\Scripts\\python.exe. Run .\\scripts\\setup.ps1 first."
    }

    $env:GRAPH_BACKEND = "fuseki"
    $env:FUSEKI_BASE_URL = $FusekiBaseUrl
    $env:FUSEKI_DATASET = $Dataset
    $env:FUSEKI_USERNAME = $Username
    $env:FUSEKI_PASSWORD = $Password

    Write-Host "Using GRAPH_BACKEND=$($env:GRAPH_BACKEND)"

    Write-Host "[1/7] Starting Fuseki container..."
    docker compose up -d

    Write-Host "[2/7] Waiting for Fuseki readiness..."
    Wait-FusekiReady -BaseUrl $FusekiBaseUrl -User $Username -Pass $Password -TimeoutSeconds $StartupTimeoutSeconds

    if ($ResetFirst) {
        Write-Host "[3/7] Resetting Fuseki dataset graph content..."
        $pair = "$Username`:$Password"
        $basicToken = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
        $headers = @{ Authorization = "Basic $basicToken" }
        $encodedDefault = [System.Uri]::EscapeDataString("default")
        Invoke-WebRequest -Uri "$FusekiBaseUrl/$Dataset/data?default" -Method Delete -Headers $headers -UseBasicParsing | Out-Null
        foreach ($graph in @("urn:graph:raw", "urn:graph:asserted", "urn:graph:inferred", "urn:graph:validation-reports")) {
            $encodedGraph = [System.Uri]::EscapeDataString($graph)
            Invoke-WebRequest -Uri "$FusekiBaseUrl/$Dataset/data?graph=$encodedGraph" -Method Delete -Headers $headers -UseBasicParsing | Out-Null
        }
    }

    if ([string]::IsNullOrWhiteSpace($InputTextPath)) {
        Write-Host "[4/7] Loading sample raw graph into Fuseki..."
        powershell -ExecutionPolicy Bypass -File .\scripts\load-sample.ps1 -Backend fuseki -Dataset $Dataset -FusekiBaseUrl $FusekiBaseUrl -Username $Username -Password $Password
    }
    else {
        if (-not (Test-Path $InputTextPath)) {
            throw "Input text file not found: $InputTextPath"
        }
        Write-Host "[4/7] Running extraction pipeline from unstructured input..."
        & $pythonExe -m extraction_pipeline.cli --input $InputTextPath --backend fuseki --dataset $Dataset --base-url $FusekiBaseUrl --username $Username --password $Password
    }

    Write-Host "[5/7] Validating and promoting raw -> asserted..."
    & $pythonExe -m validation_gate.cli --backend fuseki --dataset $Dataset --base-url $FusekiBaseUrl --username $Username --password $Password

    Write-Host "[6/7] Materializing inferred graph..."
    & $pythonExe -m validation_gate.infer --backend fuseki --dataset $Dataset --base-url $FusekiBaseUrl --username $Username --password $Password

    Write-Host "[7/7] Verifying graph counts and running QA smoke question..."
    powershell -ExecutionPolicy Bypass -File .\scripts\verify-graph.ps1 -Backend fuseki -Dataset $Dataset -FusekiBaseUrl $FusekiBaseUrl -Username $Username -Password $Password
    & $pythonExe -c "from qa_service.sparql import ask_fuseki; r=ask_fuseki('Who are the customers?'); print(r.answer); print(r.rows[:3])"

    if ($LaunchApi) {
        Write-Host "Launching QA API at http://127.0.0.1:8000 ..."
        uvicorn qa_service.main:app --app-dir .\qa\src --reload
    }
    else {
        Write-Host "Fuseki demo complete. Use -LaunchApi to start the QA service."
    }
}
finally {
    Pop-Location
}
