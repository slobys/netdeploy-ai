# Enable an isolated Codex Worker for the Windows localhost NetDeploy instance.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw '未检测到 Docker Desktop。请先安装并启动 Linux 容器引擎。'
    }
    & docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop 尚未启动，请启动后重试。' }
    $envFile = Join-Path $root '.env'
    if (-not (Test-Path $envFile)) {
        throw '请先运行一次 QuickStart-NetDeploy.bat 初始化管理员令牌。'
    }
    $lines = @(Get-Content -Path $envFile -Encoding UTF8)
    $admin = $null
    $worker = $null
    foreach ($line in $lines) {
        if ($line -match '^NETDEPLOY_ADMIN_TOKEN=(.*)$') { $admin = $Matches[1].Trim('"', "'") }
        if ($line -match '^NETDEPLOY_WORKER_TOKEN=(.*)$') { $worker = $Matches[1].Trim('"', "'") }
    }
    if ([string]::IsNullOrWhiteSpace($admin) -or $admin.Length -lt 24) {
        throw '管理员令牌缺失。请先运行 QuickStart-NetDeploy.bat。'
    }
    if ([string]::IsNullOrWhiteSpace($worker) -or $worker.Length -lt 24 -or $worker.StartsWith('REPLACE_')) {
        if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
            throw '未检测到 Python 启动器 py，无法安全生成 Worker 令牌。'
        }
        $worker = (& py -c 'import secrets; print(secrets.token_urlsafe(40))').Trim()
        if ($LASTEXITCODE -ne 0) { throw '生成 Worker 令牌失败。' }
        $lines = @($lines | Where-Object { $_ -notmatch '^NETDEPLOY_WORKER_TOKEN=' })
        $lines += "NETDEPLOY_WORKER_TOKEN=$worker"
        [System.IO.File]::WriteAllLines($envFile, $lines, [System.Text.UTF8Encoding]::new($false))
    }
    $env:NETDEPLOY_ADMIN_TOKEN = $admin
    $env:NETDEPLOY_WORKER_TOKEN = $worker
    Write-Host '[NetDeploy AI] 正在构建隔离的 Codex Worker（仅监听本机 127.0.0.1:8788）...'
    & docker compose -f compose.yaml -f compose.ai-windows.yaml --profile ai up -d --build codex-worker
    if ($LASTEXITCODE -ne 0) { throw 'AI Worker 启动失败。请检查 Docker Desktop 和镜像下载。' }
    Write-Host '[NetDeploy AI] Codex Worker 已启用；请重新启动 QuickStart-NetDeploy.bat，再从左侧 Codex AI 登录 ChatGPT。' -ForegroundColor Green
} catch {
    Write-Host "[NetDeploy AI] 错误：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}