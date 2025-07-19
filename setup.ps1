# PowerShell setup script for tetra-decode
# Install Zadig via Chocolatey when available
if (Get-Command choco -ErrorAction SilentlyContinue) {
    choco install -y zadig
} else {
    Write-Host "Chocolatey not found. Please install Zadig manually or install Chocolatey from https://chocolatey.org/install."
}

Write-Host "Please install rtl-sdr drivers and osmocom-tetra tools manually."

# Install Python dependencies
pip install -r requirements.txt
