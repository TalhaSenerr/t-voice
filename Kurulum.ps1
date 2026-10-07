$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv gerekli: https://docs.astral.sh/uv/getting-started/installation/ adresinden kurun.'
}
uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'Bagimlilik kurulumu basarisiz.' }
Write-Output 'T-Voice hazir. Baslat.cmd ile uygulamayi acabilirsiniz.'
