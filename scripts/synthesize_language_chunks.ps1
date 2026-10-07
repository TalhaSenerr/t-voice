param(
    [Parameter(Mandatory = $true)][string]$ChunksJson
)
$ErrorActionPreference = 'Stop'
$chunks = Get-Content -LiteralPath $ChunksJson -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($chunk in $chunks) {
    $voice = $null
    $stream = $null
    $token = $null
    try {
        $voice = New-Object -ComObject SAPI.SpVoice
        if ($chunk.language -eq 'tr') {
            $token = New-Object -ComObject SAPI.SpObjectToken
            $token.SetId('HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_trTR_Tolga')
        } else {
            $token = $voice.GetVoices() | Where-Object { $_.GetDescription() -like '*Zira*' } | Select-Object -First 1
            if ($null -eq $token) { throw 'Installed Microsoft Zira Desktop voice was not found.' }
        }
        $voice.Voice = $token
        $stream = New-Object -ComObject SAPI.SpFileStream
        $stream.Open([string]$chunk.path, 3, $false)
        $voice.AudioOutputStream = $stream
        $null = $voice.Speak([string]$chunk.text)
        $stream.Close()
        Write-Output ('Synthesized locally: ' + [System.IO.Path]::GetFileName([string]$chunk.path))
    } finally {
        if ($null -ne $stream) {
            try { $stream.Close() } catch { }
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($stream)
        }
        if ($null -ne $voice) { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($voice) }
        if ($null -ne $token) { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($token) }
    }
}
