# Isolated Codex Worker bootstrap. -Auto is non-blocking for the parent starter.
# It may launch Docker Desktop, but never starts the NetDeploy API container.
param([switch]$Auto)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

function Write-CodexStartupState {
    param([string]$State, [string]$Message)
    try {
        $data = Join-Path $root 'data'
        [void][System.IO.Directory]::CreateDirectory($data)
        $value = @{ state = $State; message = $Message; epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
        $json = ConvertTo-Json -InputObject $value -Compress
        [System.IO.File]::WriteAllText(
            (Join-Path $data 'codex-worker-startup.json'), $json, [System.Text.UTF8Encoding]::new($false))
    } catch {
        # Status is advisory; a failed write must not prevent VPS startup.
    }
}

function Find-DockerCommand {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidate = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    return $null
}

function Get-LocalDockerContexts {
    param([string]$DockerExe)
    # Docker Desktop may leave "default" selected when it is stopped.
    # Context inspection is local metadata, not proof the engine is running.
    # Only allow the known localhost named pipes. Never select SSH/TCP Docker.
    foreach ($name in @('desktop-linux', 'default')) {
        try {
            $endpoints = @(& $DockerExe context inspect $name --format '{{.Endpoints.docker.Host}}' 2>$null)
            if ($LASTEXITCODE -ne 0 -or $endpoints.Count -ne 1) { continue }
            $endpoint = ([string]$endpoints[0]).Trim()
            if ($endpoint -match '(?i)^npipe:/{2,4}\./pipe/(dockerDesktopLinuxEngine|docker_engine)$') {
                Write-Output $name
            }
        } catch {
            # A missing context is ordinary before Docker Desktop's first launch.
        }
    }
}

function Get-DockerServerOs {
    param([string]$DockerExe, [string]$Context)
    # Distinguish a booting engine from a Windows-container engine.
    # Every invocation explicitly targets a verified LOCAL context.
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $DockerExe
    $process.StartInfo.Arguments = '--context "' + $Context + '" info --format "{{.OSType}}"'
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    try {
        if (-not $process.Start()) { return $null }
        if (-not $process.WaitForExit(3500)) {
            try { $process.Kill() } catch {}
            return $null
        }
        if ($process.ExitCode -ne 0) { return $null }
        $os = $process.StandardOutput.ReadToEnd().Trim().ToLowerInvariant()
        if ($os -in @('linux', 'windows')) { return $os }
        return $null
    } catch {
        return $null
    } finally {
        $process.Dispose()
    }
}

function Find-RunningLocalLinuxContext {
    param([string]$DockerExe)
    foreach ($name in @(Get-LocalDockerContexts $DockerExe)) {
        if ((Get-DockerServerOs $DockerExe $name) -eq 'linux') {
            return $name
        }
    }
    return $null
}

function Test-WindowsContainerMode {
    param([string]$DockerExe)
    foreach ($name in @(Get-LocalDockerContexts $DockerExe)) {
        if ((Get-DockerServerOs $DockerExe $name) -eq 'windows') {
            return $true
        }
    }
    return $false
}

function Invoke-BoundedCompose {
    param([string]$DockerExe, [string[]]$Arguments)
    # First-time downloads can be slow, but cannot run forever in the background.
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $DockerExe
    $process.StartInfo.Arguments = ($Arguments -join ' ')
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    try {
        if (-not $process.Start()) { return $false }
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        if (-not $process.WaitForExit(420000)) {
            try { $process.Kill() } catch {}
            return $false
        }
        return ($process.ExitCode -eq 0)
    } catch {
        return $false
    } finally {
        $process.Dispose()
    }
}

function Find-DockerDesktop {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker Desktop.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

$mutex = $null
$lockHeld = $false
try {
    # Prevent a second QuickStart or manual enable from racing Docker Compose.
    $mutex = New-Object System.Threading.Mutex($false, 'Local\NetDeployCodexWorkerStartup')
    try { $lockHeld = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $lockHeld = $true }
    if (-not $lockHeld) {
        Write-Host '[NetDeploy AI] Codex Worker 已在另一窗口进行启动检查。'
        return
    }

    Write-CodexStartupState 'starting' '正在检查本机 Docker 和 Codex Worker…'
    $dockerExe = Find-DockerCommand
    if (-not $dockerExe) {
        throw '未找到 Docker Desktop。可以先使用普通 VPS 管理；如需 Codex，请安装 Docker Desktop（Linux 容器）。'
    }
    # Never inherit an unrelated remote Docker context or DOCKER_HOST from the
    # user's shell. These environment changes affect only this helper process.
    # Every Docker operation below uses --context with verified LOCAL npipe.
    Remove-Item Env:DOCKER_HOST -ErrorAction SilentlyContinue
    Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue

    $envFile = Join-Path $root '.env'
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw '未找到 .env。请先正常运行一次 QuickStart-NetDeploy.bat。'
    }
    $lines = @(Get-Content -LiteralPath $envFile -Encoding UTF8)
    $admin = $null
    $worker = $null
    foreach ($line in $lines) {
        if ($line -match '^NETDEPLOY_ADMIN_TOKEN=(.*)$') { $admin = $Matches[1].Trim('"', "'") }
        if ($line -match '^NETDEPLOY_WORKER_TOKEN=(.*)$') { $worker = $Matches[1].Trim('"', "'") }
    }
    if ([string]::IsNullOrWhiteSpace($admin) -or $admin.Length -lt 24 -or
        $admin.StartsWith('REPLACE_')) {
        throw '管理员令牌尚未初始化。请先正常运行 QuickStart-NetDeploy.bat。'
    }
    if ([string]::IsNullOrWhiteSpace($worker) -or $worker.Length -lt 24 -or
        $worker.StartsWith('REPLACE_')) {
        if ($Auto) { throw 'Codex Worker 令牌尚未初始化。请先正常运行 QuickStart-NetDeploy.bat。' }
        if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
            throw '找不到 Python 启动器 py，无法生成 Worker 令牌。'
        }
        $worker = (& py -c 'import secrets;print(secrets.token_urlsafe(40))').Trim()
        if ($LASTEXITCODE -ne 0) { throw '无法生成 Codex Worker 令牌。' }
        $lines = @($lines | Where-Object { $_ -notmatch '^NETDEPLOY_WORKER_TOKEN=' })
        $lines += "NETDEPLOY_WORKER_TOKEN=$worker"
        [System.IO.File]::WriteAllLines($envFile, $lines, [System.Text.UTF8Encoding]::new($false))
    }
    $env:NETDEPLOY_ADMIN_TOKEN = $admin
    $env:NETDEPLOY_WORKER_TOKEN = $worker

    # A named local context is not proof that Docker Desktop is up. In
    # particular, "desktop-linux" can be absent or offline on cold boot.
    $dockerContext = Find-RunningLocalLinuxContext $dockerExe
    if (-not $dockerContext) {
        if (Test-WindowsContainerMode $dockerExe) {
            throw 'Docker Desktop 正在使用 Windows containers。请在 Docker Desktop 菜单选择 Switch to Linux containers。'
        }
        $desktop = Find-DockerDesktop
        if (-not $desktop) {
            throw 'Docker Linux 引擎尚未就绪，且未找到 Docker Desktop。请安装并启动 Docker Desktop。'
        }
        Write-CodexStartupState 'starting' '正在启动 Docker Desktop 并等待本机 Linux 引擎；不影响 VPS 面板使用。'
        Start-Process -FilePath $desktop -ErrorAction Stop | Out-Null
        # Wait only in the isolated helper. Reinspect contexts because Docker
        # Desktop may CREATE "desktop-linux" after its first startup.
        for ($i = 0; $i -lt 45; $i++) {
            Start-Sleep -Seconds 2
            $dockerContext = Find-RunningLocalLinuxContext $dockerExe
            if ($dockerContext) { break }
            if (Test-WindowsContainerMode $dockerExe) {
                throw 'Docker Desktop 已启动，但当前是 Windows containers。请切换到 Linux containers。'
            }
        }
        if (-not $dockerContext) {
            throw 'Docker Desktop 尚未提供本机 Linux 引擎。请检查 WSL 2、Docker Desktop 的 Linux 容器模式并重新启动。'
        }
    }

    $sources = @(
        'Dockerfile.ai', 'requirements.txt', 'app\ai_worker.py',
        'compose.yaml', 'compose.ai-windows.yaml'
    )
    $fingerprint = ($sources | ForEach-Object {
        (Get-FileHash -LiteralPath (Join-Path $root $_) -Algorithm SHA256).Hash
    }) -join ':'
    $marker = Join-Path $root 'data\codex-worker-build.sha256'
    $needsBuild = (-not (Test-Path -LiteralPath $marker -PathType Leaf)) -or
        ((Get-Content -LiteralPath $marker -Raw).Trim() -ne $fingerprint)
    Write-CodexStartupState 'starting' '正在检查或启动 Codex Worker；首次使用及软件更新后可能需要构建镜像。'
    $composeArgs = @('--context', $dockerContext, 'compose', '-f', 'compose.yaml', '-f', 'compose.ai-windows.yaml',
                     '--profile', 'ai', 'up', '-d', '--no-deps')
    if ($needsBuild) { $composeArgs += '--build' }
    $composeArgs += 'codex-worker'
    # Only the isolated worker, never the netdeploy service or its port 8787.
    if (-not (Invoke-BoundedCompose $dockerExe $composeArgs)) {
        throw 'Codex Worker 容器启动失败或超时。请检查 Docker Desktop、磁盘空间和镜像下载。'
    }

    $ready = $false
    for ($i = 0; $i -lt 16; $i++) {
        try {
            $result = Invoke-RestMethod -Uri 'http://127.0.0.1:8788/account/status' `
                -Headers @{ 'X-Worker-Token' = $worker } -TimeoutSec 3
            if ($result.available -eq $true) { $ready = $true; break }
        } catch {
            # Container service may still be starting; never print worker token.
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Codex Worker 尚未响应。请在后台 Codex AI 中刷新，或检查容器状态。' }
    [System.IO.File]::WriteAllText($marker, $fingerprint, [System.Text.UTF8Encoding]::new($false))
    Write-CodexStartupState 'ready' 'Codex Worker 已就绪。ChatGPT 登录状态将自动复用。'
    Write-Host '[NetDeploy AI] Codex Worker 已就绪；无需单独打开 Codex，也无需重复授权。' -ForegroundColor Green
} catch {
    # Do not disclose paths, tokens, Docker output, or stack traces to the UI.
    $reason = $_.Exception.Message
    Write-CodexStartupState 'failed' $reason
    if ($Auto) {
        Write-Warning ("[NetDeploy AI] Codex 可选服务未就绪：" + $reason + "。普通 VPS 功能不受影响。")
    } else {
        Write-Host ("[NetDeploy AI] Codex 启动失败：" + $reason) -ForegroundColor Red
        exit 1
    }
} finally {
    if ($lockHeld -and $null -ne $mutex) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
