param(
    [switch]$Offline,
    [switch]$Portfolio,
    [ValidateSet('normal','machine_overheat','environmental_fire_high','combined_critical','stale_device')]
    [string]$Scenario = 'combined_critical',
    [int]$BackendPort = 5000,
    [int]$FrontendPort = 3000,
    [switch]$EnableAlertActions,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
if ($Offline -and $Portfolio) { throw 'Escolha -Offline ou -Portfolio; os modos não são intercambiáveis.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$frontend = Join-Path $projectRoot 'frontend'
$artifacts = Join-Path $frontend 'artifacts'
function Port-Free([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $listener.Start(); return $true } catch { return $false } finally { $listener.Stop() }
}
if (!(Test-Path -LiteralPath $python)) { throw 'Crie .venv e instale requirements.txt antes de iniciar.' }
$node = (Get-Command node -ErrorAction Stop).Source
if (!(Test-Path -LiteralPath (Join-Path $frontend 'node_modules\next\dist\bin\next'))) { throw 'Execute npm ci em frontend.' }
if (!(Port-Free $BackendPort)) { throw "Porta backend $BackendPort ocupada. Use -BackendPort com uma porta livre; nenhum processo foi encerrado." }
if (!(Port-Free $FrontendPort)) {
    $candidate = @(3100,3101,3102 | Where-Object { Port-Free $_ } | Select-Object -First 1)
    if (!$candidate.Count) { throw 'Portas frontend ocupadas. Escolha -FrontendPort.' }
    $FrontendPort = $candidate[0]
    Write-Host "WARNING porta frontend ocupada; usando $FrontendPort."
}
Push-Location $projectRoot
try {
    $firebaseOk = & $python -c 'from config import Config; from pathlib import Path; print(Path(Config.FIREBASE_KEY_PATH).is_file())'
    if ($LASTEXITCODE -ne 0) { throw 'Configuração Python inválida; verifique .env sem divulgar credenciais.' }
    if ($firebaseOk -ne 'True') {
        if (!$Offline -and !$Portfolio) { throw 'Credencial Firebase ausente. Configure FIREBASE_KEY_PATH ou use -Offline/-Portfolio.' }
        Write-Host 'WARNING Firebase ausente; estados persistidos ficam indisponíveis. O modo selecionado permanece explícito.'
    }
    Write-Host "PASS Python, Next e portas disponíveis: backend $BackendPort / frontend $FrontendPort."
    if ($CheckOnly) { return }
    New-Item -ItemType Directory -Path $artifacts -Force | Out-Null
    $names = @('HOST','PORT','ENVIRONMENT','APP_API_KEYS','ALLOW_DEV_AUTH_BYPASS','ALLOW_DEV_DEVICE_BYPASS','SOMPO_BACKEND_URL','SOMPO_BACKEND_API_KEY','SOMPO_ENABLE_ALERT_ACTIONS','SOMPO_DEMO_SCENARIO_PATH','TELEGRAM_NOTIFICATIONS_ENABLED')
    $saved = @{}
    foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
    try {
        # Ephemeral application key shared only by these child processes; never logged or persisted.
        $localKey = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
        $env:HOST = '127.0.0.1'; $env:PORT = "$BackendPort"; $env:ENVIRONMENT = 'development'
        $env:APP_API_KEYS = $localKey; $env:SOMPO_BACKEND_API_KEY = $localKey
        $env:ALLOW_DEV_AUTH_BYPASS = 'false'; $env:ALLOW_DEV_DEVICE_BYPASS = 'false'
        $env:SOMPO_BACKEND_URL = "http://127.0.0.1:$BackendPort"
        $env:SOMPO_ENABLE_ALERT_ACTIONS = if ($EnableAlertActions -and !$Offline -and !$Portfolio) { 'true' } else { 'false' }
        if ($Offline -or $Portfolio) { $env:TELEGRAM_NOTIFICATIONS_ENABLED = 'false' }
        $env:SOMPO_DEMO_SCENARIO_PATH = ''
        if ($Offline) {
            $env:SOMPO_DEMO_SCENARIO_PATH = Join-Path $artifacts 'demo-scenario.json'
            & $python -m scripts.seed_demo --export $env:SOMPO_DEMO_SCENARIO_PATH --scenario $Scenario
            if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar cenário offline.' }
        }
        $backendProcess = Start-Process -FilePath $python -ArgumentList 'server.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $artifacts 'backend.log') -RedirectStandardError (Join-Path $artifacts 'backend-error.log') -PassThru
        $frontendProcess = Start-Process -FilePath $node -ArgumentList 'node_modules/next/dist/bin/next','dev','--hostname','127.0.0.1','--port',"$FrontendPort" -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $artifacts 'frontend.log') -RedirectStandardError (Join-Path $artifacts 'frontend-error.log') -PassThru
        $frontendUrl = "http://127.0.0.1:$FrontendPort" + $(if ($Offline) { '/?mode=demo' } elseif ($Portfolio) { '/?mode=portfolio' } else { '/' })
        $ready = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            try {
                $null = Invoke-WebRequest "http://127.0.0.1:$BackendPort/health" -UseBasicParsing -TimeoutSec 2
                $null = Invoke-WebRequest $frontendUrl -UseBasicParsing -TimeoutSec 3
                $ready = $true; break
            } catch { Start-Sleep -Milliseconds 500 }
        }
        if ($ready) { Write-Host 'PASS backend e frontend respondem.' } else { Write-Host 'WARNING startup incompleto; confira os logs em frontend/artifacts.' }
        Write-Host "Backend: http://127.0.0.1:$BackendPort (PID $($backendProcess.Id))"
        Write-Host "Frontend: $frontendUrl (PID $($frontendProcess.Id))"
        if ($Offline -or $Portfolio) { Write-Host 'Telegram desabilitado. Nenhum seed Firebase foi executado.' }
        else { Write-Host 'Telegram usa configuração do servidor; entrega exige worker explícito. Nenhum seed Firebase foi executado.' }
        Write-Host 'Para encerrar, use somente os PIDs acima; o Next pode ter um processo filho.'
    } finally {
        foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
        $localKey = $null
    }
} finally { Pop-Location }
