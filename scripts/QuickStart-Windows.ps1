# QuickStart: run only from a verified Git clone. Do not modify data or secrets.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw '请先安装 Git for Windows，随后重新执行一键启动命令。'
    }
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw '请先安装 Python 3.12 或更新版本，并启用 Windows py 启动器。'
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
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort 8787 -ErrorAction SilentlyContinue
        if ($listener) {
            try {
                $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/api/health' -TimeoutSec 3
                if ($health.ok -and $health.version) {
                    Write-Host '[NetDeploy AI] 已检测到正在运行的面板。请先停止旧服务才能更新。' -ForegroundColor Yellow
                    Start-Process 'http://127.0.0.1:8787'
                    exit 0
                }
            } catch {}
            throw '本机 8787 端口被其他程序占用。请先关闭占用程序，避免误打开其他应用。'
        }
    }
    Write-Host '[NetDeploy AI] 正在安全检查 GitHub 更新（不覆盖 data/.env/known_hosts）...'
    $update = Join-Path $root 'scripts\Update-Windows.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $update
    if ($LASTEXITCODE -ne 0) { throw '自动更新未完成；不会跳过 Git 安全检查。请查看上面的错误。' }
    Write-Host '[NetDeploy AI] 正在启动本机控制台并自动打开浏览器...' -ForegroundColor Green
    & (Join-Path $root 'Start-NetDeploy.bat')
    if ($LASTEXITCODE -ne 0) { throw '启动失败，请查看 Start-NetDeploy 输出。' }
} catch {
    Write-Host ("[NetDeploy AI] 一键启动中止：" + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
