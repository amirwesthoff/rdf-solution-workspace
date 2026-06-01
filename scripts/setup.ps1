Write-Host "Creating virtual environment..."
py -m venv .venv

Write-Host "Activating virtual environment..."
.\.venv\Scripts\Activate.ps1

Write-Host "Installing editable packages..."
pip install -e .\extraction -e .\validation -e .\qa

Write-Host "Setup complete."
