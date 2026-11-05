# QuickStart: run only from a verified Git clone. Do not modify data or secrets.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'Windows-Loopback.ps1')
$panelUrl = 'http://127.0.0.1:8787'
$launcherLock = [System.Threading.Mutex]::new($false, 'Local\NetDeployAI.QuickStart.8787')
$lockAcquired = $false

function Get-NetDeployPanelVersion {
    try {
        $health = Invoke-RestMethod -Uri "$panelUrl/api/health" -TimeoutSec 2 -MaximumRedirection 0
        if ($health.ok -is [bool] -and $health.ok -and $health.security -ceq 'local-only' -and
            $health.version -match '^\d+\.\d+\.\d+$') {
            return [string]$health.version
        }
    } catch {
        # A different local service can be bound to the same port.
    }
}

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw '请先安装 Git for Windows，随后重新执行一键启动命令。'
    }
    $top = (& git -C $root rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $top -or
        ([System.IO.Path]::GetFullPath($top.Trim()).TrimEnd('\','/') -ine
         [System.IO.Path]::GetFullPath($root).TrimEnd('\','/'))) {
        throw '当前目录不是正确的 NetDeploy AI Git 克隆目录。'
    }
    $origin = (& git -C $root remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or
        $origin -notmatch '(^https://github\.com/slobys/netdeploy-ai(\.git)?$|^git@github\.com:slobys/netdeploy-ai(\.git)?$)') {
        throw 'GitHub origin 地址不正确，拒绝执行不可信代码。'
    }
    try {
        $lockAcquired = $launcherLock.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $lockAcquired = $true
    }
    if (-not $lockAcquired) {
        Write-Host '[NetDeploy AI] 另一个 QuickStart 正在启动面板。'
        return
    }
    if (-not (Test-NetDeployPortAvailable)) {
        $runningVersion = Get-NetDeployPanelVersion
        if (-not $runningVersion) {
            throw '本机 8787 无法绑定，且未检测到 NetDeploy AI。请检查端口占用。'
        }
        Write-Host "[NetDeploy AI] 打开正在运行的 v$runningVersion。停止面板后再次启动即可检查更新。"
        Start-Process $panelUrl
        return
    }
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw '请先安装 Python 3.12 或更新版本，并启用 Windows py 启动器。'
    }
    Write-Host '[NetDeploy AI] 正在安全检查 GitHub 更新（不覆盖 data/.env/known_hosts）...'
    $update = Join-Path $root 'scripts\Update-Windows.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $update
    if ($LASTEXITCODE -ne 0) { throw '自动更新未完成；不会跳过 Git 安全检查。请查看上面的错误。' }
    Write-Host '[NetDeploy AI] 正在后台启动面板...'
    $logDir = Join-Path $root '.build'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdout = Join-Path $logDir 'quickstart.stdout.log'
    $stderr = Join-Path $logDir 'quickstart.stderr.log'
    $starter = Join-Path $root 'scripts\Start-Windows.ps1'
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $service = Start-Process -FilePath $powershell -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $starter + '"'), '-Background' -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    while (-not $service.HasExited) {
        if (Get-NetDeployPanelVersion) {
            Start-Process $panelUrl
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "面板启动失败。请查看 $stdout 和 $stderr。"
} catch {
    Write-Host ("[NetDeploy AI] 一键启动中止：" + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($lockAcquired) { $launcherLock.ReleaseMutex() }
    $launcherLock.Dispose()
}
