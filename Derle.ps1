$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'Bagimliliklar hazirlanamadi.' }
& .\.venv\Scripts\python.exe scripts\release_assets.py
if ($LASTEXITCODE -ne 0) { throw 'Paket varliklari olusturulamadi.' }
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Testler basarisiz; derleme durduruldu.' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm T-Voice.spec
if ($LASTEXITCODE -ne 0) { throw 'Paketleme basarisiz.' }
& .\.venv\Scripts\python.exe scripts\assemble_release.py
if ($LASTEXITCODE -ne 0) { throw 'Paket tamamlanamadi.' }
Write-Output 'Hazir: dist\T-Voice\T-Voice.exe'
