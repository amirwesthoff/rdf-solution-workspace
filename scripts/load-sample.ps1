param(
	[string]$Dataset = "kg",
	[string]$Graph = "urn:graph:raw",
	[string]$FusekiBaseUrl = "http://localhost:3030",
	[string]$Username = "admin",
	[string]$Password = "admin",
	[string]$Backend = ""
)

if ([string]::IsNullOrWhiteSpace($Backend)) {
	$Backend = $env:GRAPH_BACKEND
}
if ([string]::IsNullOrWhiteSpace($Backend)) {
	$Backend = "rdflib"
}
$Backend = $Backend.ToLowerInvariant()

$samplePath = Join-Path $PSScriptRoot "..\contracts\sample-data\sample.ttl"
$samplePath = (Resolve-Path $samplePath).Path

if (-not (Test-Path $samplePath)) {
	throw "Sample data file not found: $samplePath"
}

if ($Backend -eq "rdflib") {
	$storeDir = Join-Path $PSScriptRoot "..\data\graph-store"
	$storeDir = (Resolve-Path (New-Item -ItemType Directory -Force -Path $storeDir)).Path

	$graphFile = "raw.ttl"
	if ($Graph -eq "urn:graph:asserted") { $graphFile = "asserted.ttl" }
	elseif ($Graph -eq "urn:graph:inferred") { $graphFile = "inferred.ttl" }
	elseif ($Graph -eq "urn:graph:validation-reports") { $graphFile = "validation-reports.ttl" }

	$targetPath = Join-Path $storeDir $graphFile
	Copy-Item -Path $samplePath -Destination $targetPath -Force
	Write-Host "Sample data copied to on-disk graph '$Graph' at $targetPath"
}
elseif ($Backend -eq "fuseki") {
	$encodedGraph = [System.Uri]::EscapeDataString($Graph)
	$graphStoreUrl = "$FusekiBaseUrl/$Dataset/data?graph=$encodedGraph"

	$pair = "$Username`:$Password"
	$basicToken = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
	$headers = @{ Authorization = "Basic $basicToken" }

	Write-Host "Uploading sample RDF to $graphStoreUrl"
	Invoke-WebRequest `
		-Uri $graphStoreUrl `
		-Method Put `
		-Headers $headers `
		-InFile $samplePath `
		-ContentType "text/turtle" `
		-UseBasicParsing

	Write-Host "Sample data loaded into graph '$Graph'."
}
else {
	throw "Unsupported backend '$Backend'. Use 'rdflib' (default) or 'fuseki'."
}

if (Test-Path (Join-Path $PSScriptRoot "verify-graph.ps1")) {
	Write-Host "Verifying named graph counts..."
	& (Join-Path $PSScriptRoot "verify-graph.ps1") `
		-Backend $Backend `
		-Dataset $Dataset `
		-FusekiBaseUrl $FusekiBaseUrl `
		-Username $Username `
		-Password $Password
}
