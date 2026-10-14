# Diagnóstico USB para celulares Android / MediaTek (ex.: Infinix Hot 11S X6812B)
# Fica monitorando as portas USB e registra cada vez que o celular aparece ou some,
# dizendo em que modo ele está. Ideal para aparelhos em bootloop.

$ErrorActionPreference = 'SilentlyContinue'
$logFile = Join-Path $PSScriptRoot ("diagnostico-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".log")

function Get-Mode($id, $name) {
    switch -Regex ($id) {
        'VID_0E8D&PID_0003' { return 'BROM (modo de emergência MediaTek) - dá para regravar tudo com mtkclient/SP Flash Tool' }
        'VID_0E8D&PID_2000' { return 'PRELOADER MediaTek - o chip está vivo; dá para regravar o firmware com SP Flash Tool/mtkclient' }
        'VID_18D1&PID_4EE0' { return 'FASTBOOT - dá para desbloquear o bootloader e gravar imagens' }
        'VID_18D1&PID_D00D' { return 'FASTBOOT - dá para desbloquear o bootloader e gravar imagens' }
    }
    if ($name -match 'fastboot|bootloader') { return 'FASTBOOT - dá para desbloquear o bootloader e gravar imagens' }
    if ($name -match 'ADB')                 { return 'ADB - o Android (ou o recovery) está rodando' }
    if ($name -match 'MTP|Infinix|Android') { return 'SISTEMA ANDROID (MTP) - o celular chegou a ligar' }
    if ($name -match 'Preloader')           { return 'PRELOADER MediaTek - o chip está vivo' }
    if ($id -match 'VID_0E8D')              { return 'Dispositivo MediaTek (modo não identificado)' }
    return $null
}

function Get-UsbDevices {
    $list = @{}
    Get-CimInstance Win32_PnPEntity -Filter "PNPDeviceID LIKE 'USB\\VID_%'" | ForEach-Object {
        $list[$_.PNPDeviceID] = $_
    }
    return $list
}

function Write-Log($msg, $color = 'Gray') {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss.fff'), $msg
    Write-Host $line -ForegroundColor $color
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Clear-Host
Write-Host '=============================================================' -ForegroundColor Cyan
Write-Host '  Diagnóstico USB - Android / MediaTek' -ForegroundColor Cyan
Write-Host '=============================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Como usar:'
Write-Host '  1. Deixe esta janela aberta.'
Write-Host '  2. Conecte o celular ao PC com um cabo de DADOS (não só de carga).'
Write-Host '  3. Deixe ele reiniciar algumas vezes. Depois tente também:'
Write-Host '       - segurar VOLUME + e VOLUME - juntos enquanto conecta o cabo'
Write-Host '       - segurar POWER + VOLUME + até aparecer algo (recovery)'
Write-Host '  4. Aperte Ctrl+C para encerrar e ver o resumo.'
Write-Host ''
Write-Host "Log salvo em: $logFile" -ForegroundColor DarkGray
Write-Host ''

$before = Get-UsbDevices
$seen = @{}
Write-Log ("Monitorando... ({0} dispositivos USB já conectados serão ignorados)" -f $before.Count) 'DarkGray'

try {
    while ($true) {
        Start-Sleep -Milliseconds 250
        $now = Get-UsbDevices

        foreach ($id in $now.Keys) {
            if (-not $before.ContainsKey($id)) {
                $dev  = $now[$id]
                $name = if ($dev.Name) { $dev.Name } else { '(sem nome)' }
                $mode = Get-Mode $id $name
                if ($mode) {
                    Write-Log ("CONECTOU  -> {0}" -f $mode) 'Green'
                    $seen[$mode] = 1 + [int]$seen[$mode]
                } else {
                    Write-Log ("CONECTOU  -> dispositivo USB desconhecido") 'Yellow'
                }
                Write-Log ("             {0}  [{1}]  status: {2}" -f $name, $id, $dev.Status) 'DarkGray'
                if ($dev.Status -ne 'OK') {
                    Write-Log '             Atenção: o Windows não tem driver para este modo (normal para Preloader/BROM sem drivers MTK).' 'Yellow'
                }
            }
        }
        foreach ($id in $before.Keys) {
            if (-not $now.ContainsKey($id)) {
                $name = $before[$id].Name
                Write-Log ("DESCONECTOU <- {0}" -f $name) 'DarkYellow'
            }
        }
        $before = $now
    }
}
finally {
    Write-Host ''
    Write-Host '======================== RESUMO ========================' -ForegroundColor Cyan
    if ($seen.Count -eq 0) {
        Write-Host 'Nenhum modo Android/MediaTek foi detectado.' -ForegroundColor Yellow
        Write-Host '- Teste outro cabo (muitos cabos são só de carga) e outra porta USB.'
        Write-Host '- Deixe o celular carregando 1-2 horas na tomada e tente de novo.'
    } else {
        foreach ($k in $seen.Keys) { Write-Host (" {0}x  {1}" -f $seen[$k], $k) -ForegroundColor Green }
        Write-Host ''
        Write-Host 'Mande este resumo (ou o arquivo .log) para o Claude para o próximo passo.'
    }
    Write-Host "Log: $logFile" -ForegroundColor DarkGray
}
