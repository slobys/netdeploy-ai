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
        Write-Host ''
        Write-Host '[NetDeploy AI] 首次启动管理员令牌（请安全保存，勿发送他人）：' -ForegroundColor Yellow
        Write-Host $savedToken -ForegroundColor Yellow
        Write-Host '[NetDeploy AI] 令牌已保存在本地 .env 中（Git 不跟踪此文件）。' -ForegroundColor Yellow
        Write-Host ''
    }
    $env:NETDEPLOY_ADMIN_TOKEN = $savedToken
    $env:NETDEPLOY_DATA = Join-Path $root 'data'
    New-Item -Path $env:NETDEPLOY_DATA -ItemType Directory -Force | Out-Null

    Write-Host '[NetDeploy AI] 本地地址：http://127.0.0.1:8787' -ForegroundColor Green
    Write-Host '[NetDeploy AI] 按 Ctrl+C 可以停止服务。'
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1
    if ($LASTEXITCODE -ne 0) { throw "服务启动失败，退出代码：$LASTEXITCODE" }
} catch {
    Write-Host "[NetDeploy AI] 错误：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
