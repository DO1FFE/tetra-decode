# PowerShell setup script for tetra-decode
# Install SDR tools on Windows using Chocolatey when available
if (Get-Command choco -ErrorAction SilentlyContinue) {
    choco install -y zadig rtl-sdr osmocom-tetra
} else {
    Write-Host "Chocolatey not found. Please install rtl-sdr drivers and osmocom-tetra tools manually or install Chocolatey from https://chocolatey.org/install."
}

# Install Python dependencies
pip install -r requirements.txt
