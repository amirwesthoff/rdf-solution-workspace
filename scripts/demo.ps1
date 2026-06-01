param(
	[string]$InputTextPath = "",
	[switch]$ResetFirst,
	[switch]$LaunchApi
)

$ErrorActionPreference = "Stop"

$repoRoot = Join-Path $PSScriptRoot ".."
Push-Location $repoRoot

try {
	$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
	if (-not (Test-Path $pythonExe)) {
		throw "Python executable not found at .venv\\Scripts\\python.exe. Run .\\scripts\\setup.ps1 first."
	}

	if ([string]::IsNullOrWhiteSpace($env:GRAPH_BACKEND)) {
		$env:GRAPH_BACKEND = "rdflib"
	}
	if ($env:GRAPH_BACKEND.ToLowerInvariant() -ne "rdflib") {
		throw "scripts/demo.ps1 is for rdflib mode. Set GRAPH_BACKEND=rdflib and retry."
	}

	Write-Host "Using GRAPH_BACKEND=$($env:GRAPH_BACKEND)"

	if ($ResetFirst) {
		Write-Host "[1/6] Resetting on-disk graph store..."
		powershell -ExecutionPolicy Bypass -File .\scripts\reset-graph-store.ps1
	}

	if ([string]::IsNullOrWhiteSpace($InputTextPath)) {
		Write-Host "[2/6] Loading sample raw graph..."
		powershell -ExecutionPolicy Bypass -File .\scripts\load-sample.ps1
	}
	else {
		if (-not (Test-Path $InputTextPath)) {
			throw "Input text file not found: $InputTextPath"
		}
		Write-Host "[2/6] Running extraction pipeline from unstructured input..."
		& $pythonExe -m extraction_pipeline.cli --input $InputTextPath
	}

	Write-Host "[3/6] Validating and promoting raw -> asserted..."
	& $pythonExe -m validation_gate.cli

	Write-Host "[4/6] Materializing inferred graph..."
	& $pythonExe -m validation_gate.infer

	Write-Host "[5/6] Verifying graph counts..."
	powershell -ExecutionPolicy Bypass -File .\scripts\verify-graph.ps1

	Write-Host "[6/6] Running QA smoke question..."
	& $pythonExe -c "from qa_service.sparql import ask_fuseki; r=ask_fuseki('Who are the customers?'); print(r.answer); print(r.rows[:3])"

	if ($LaunchApi) {
		Write-Host "Launching QA API at http://127.0.0.1:8000 ..."
		uvicorn qa_service.main:app --app-dir .\qa\src --reload
	}
	else {
		Write-Host "Demo complete. Use -LaunchApi to start the QA service."
	}
}
finally {
	Pop-Location
}
