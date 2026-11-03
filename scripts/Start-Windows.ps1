# NetDeploy AI Windows starter. Never writes credentials to the Git checkout history.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

function Require-PythonLauncher {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw '未检测到 Windows Python 启动器 py。请先安装 Python 3.12 或更新版本，并勾选 py launcher。'
    }
}

try {
    Require-PythonLauncher
    $venvPython = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython -PathType Leaf)) {
        Write-Host '[NetDeploy AI] 正在创建隔离的 Python 虚拟环境...'
        & py -m venv (Join-Path $root '.venv')
        if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败。' }
    }
    if (-not (Test-Path $venvPython -PathType Leaf)) { throw '找不到虚拟环境中的 python.exe。' }

    $reqHash = (Get-FileHash -Algorithm SHA256 (Join-Path $root 'requirements.txt')).Hash
    $marker = Join-Path $root '.venv\.requirements.sha256'
    if (-not (Test-Path $marker) -or ((Get-Content $marker -Raw).Trim() -ne $reqHash)) {
        Write-Host '[NetDeploy AI] 正在安装或更新依赖...'
        & $venvPython -m pip install -r (Join-Path $root 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败；请检查网络后重试。' }
        [System.IO.File]::WriteAllText($marker, $reqHash, [System.Text.UTF8Encoding]::new($false))
    }

    $envFile = Join-Path $root '.env'
    $savedToken = $null
    $lines = @()
    if (Test-Path $envFile) {
        $lines = @(Get-Content -Path $envFile -Encoding UTF8)
        foreach ($line in $lines) {
            if ($line -match '^NETDEPLOY_ADMIN_TOKEN=(.*)$') { $savedToken = $Matches[1].Trim('"', "'") }
        }
    }
    if ([string]::IsNullOrWhiteSpace($savedToken) -or $savedToken.Length -lt 24 -or $savedToken.StartsWith('REPLACE_')) {
        if ($env:NETDEPLOY_ADMIN_TOKEN -and $env:NETDEPLOY_ADMIN_TOKEN.Length -ge 24 -and -not $env:NETDEPLOY_ADMIN_TOKEN.StartsWith('REPLACE_')) {
            $savedToken = $env:NETDEPLOY_ADMIN_TOKEN
        } else {
            $savedToken = (& $venvPython -c 'import secrets;print(secrets.token_urlsafe(40))').Trim()
            if ($LASTEXITCODE -ne 0) { throw '无法生成管理员令牌。' }
        }
        $lines = @($lines | Where-Object { $_ -notmatch '^NETDEPLOY_ADMIN_TOKEN=' })
        $lines += "NETDEPLOY_ADMIN_TOKEN=$savedToken"
        [System.IO.File]::WriteAllLines($envFile, $lines, [System.Text.UTF8Encoding]::new($false))
        Write-Host '[NetDeploy AI] 已自动生成本机管理员令牌并保存到不受 Git 管理的 .env。'
        Write-Host '[NetDeploy AI] 本机启动时会自动登录，无需复制或输入令牌。' -ForegroundColor Green
    }
    $env:NETDEPLOY_ADMIN_TOKEN = $savedToken
    # Codex is OPTIONAL and runs in its own Docker container. Its startup is
    # dispatched to another process; Docker/WSL must never block the VPS panel.
    $autoCodex = ($env:NETDEPLOY_CODEX_AUTO_START -ne '0')
    $workerToken = $null
    foreach ($line in $lines) {
        if ($line -match '^NETDEPLOY_CODEX_AUTO_START=(.*)$') {
            if ($Matches[1].Trim('"', "'") -eq '0') { $autoCodex = $false }
        }
        if ($line -match '^NETDEPLOY_WORKER_TOKEN=(.*)$') {
            $workerToken = $Matches[1].Trim('"', "'")
        }
    }
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    $dockerAvailable = [bool]$dockerCommand
    if (-not $dockerAvailable) {
        $dockerFallback = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
        $dockerAvailable = Test-Path -LiteralPath $dockerFallback -PathType Leaf
    }
    if ($autoCodex -and $dockerAvailable -and
        ([string]::IsNullOrWhiteSpace($workerToken) -or $workerToken.Length -lt 24 -or
         $workerToken.StartsWith('REPLACE_'))) {
        $workerToken = (& $venvPython -c 'import secrets;print(secrets.token_urlsafe(40))').Trim()
        if ($LASTEXITCODE -ne 0) { throw '无法生成 Codex Worker 令牌。' }
        $lines = @($lines | Where-Object { $_ -notmatch '^NETDEPLOY_WORKER_TOKEN=' })
        $lines += "NETDEPLOY_WORKER_TOKEN=$workerToken"
        [System.IO.File]::WriteAllLines($envFile, $lines, [System.Text.UTF8Encoding]::new($false))
    }
    if ($workerToken -and $workerToken.Length -ge 24 -and
        -not $workerToken.StartsWith('REPLACE_')) {
        # Only pass the worker token to the local API. Never pass the SSH
        # secrets or panel administrator token into the Codex container.
        $env:NETDEPLOY_WORKER_TOKEN = $workerToken
        $env:NETDEPLOY_CODEX_WORKER_URL = 'http://127.0.0.1:8788'
    }
    if ($autoCodex -and $dockerAvailable -and $workerToken -and $workerToken.Length -ge 24) {
        try {
            $codexHelper = Join-Path $root 'scripts\Enable-Codex-Windows.ps1'
            $helperArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
                $codexHelper + '" -Auto'
            Start-Process -FilePath 'powershell.exe' -ArgumentList $helperArgs `
                -WindowStyle Hidden -ErrorAction Stop | Out-Null
            Write-Host '[NetDeploy AI] Codex Worker 自动启动检查已在后台开始。' -ForegroundColor Cyan
        } catch {
            Write-Warning '[NetDeploy AI] 可选 Codex 启动检查未启动；VPS 控制台仍将正常启动。'
        }
    } elseif (-not $autoCodex) {
        Write-Host '[NetDeploy AI] Codex 自动启动已关闭，VPS 控制台将照常启动。'
    } elseif (-not $dockerAvailable) {
        Write-Host '[NetDeploy AI] 未检测到 Docker Desktop，Codex 暂不可用；VPS 功能不受影响。'
    }
    # Only the trusted 127.0.0.1 listener may grant a browser local session.
    # This opt-in is never enabled by Docker/Linux startup scripts.
    $env:NETDEPLOY_LOCAL_AUTO_LOGIN = '1'
    $env:NETDEPLOY_DATA = Join-Path $root 'data'
    New-Item -Path $env:NETDEPLOY_DATA -ItemType Directory -Force | Out-Null

    Write-Host '[NetDeploy AI] 本地地址：http://127.0.0.1:8787' -ForegroundColor Green
    Write-Host '[NetDeploy AI] 服务就绪后自动打开默认浏览器；按 Ctrl+C 停止。'
    # Poll readiness from a separate PowerShell job while uvicorn runs in the
    # foreground, so the console still receives Ctrl+C and live server logs.
    $browserJob = Start-Job -ArgumentList 'http://127.0.0.1:8787' -ScriptBlock {
        param([string]$url)
        for ($i = 0; $i -lt 60; $i++) {
            try {
                $result = Invoke-WebRequest -UseBasicParsing -Uri "$url/api/health" -TimeoutSec 2
                if ($result.StatusCode -eq 200) {
                    Start-Process $url
                    break
                }
            } catch {}
            Start-Sleep -Milliseconds 500
        }
    }
    try {
        & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1
        if ($LASTEXITCODE -ne 0) { throw "服务启动失败，退出代码：$LASTEXITCODE" }
    } finally {
        if ($null -ne $browserJob) {
            Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
            Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
        }
    }
} catch {
    Write-Host "[NetDeploy AI] 错误：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
