param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][string]$Python,
    [switch]$Child
)
$ErrorActionPreference = 'Stop'
$testScript = Join-Path $PSScriptRoot '..\..\tests\smoke_windows_installer.py'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($Child -or -not $elevated) {
    if ($elevated) { throw 'Installer smoke test requires a standard Windows user' }
    if ($Child) {
        $profilePath = [Environment]::GetFolderPath('UserProfile')
        $env:USERPROFILE = $profilePath
        $env:LOCALAPPDATA = Join-Path $profilePath 'AppData\Local'
        $env:APPDATA = Join-Path $profilePath 'AppData\Roaming'
        $env:TEMP = Join-Path $env:PUBLIC 'NetDeploySmoke\temp'
        $env:TMP = $env:TEMP
        New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
    }
    $env:PYTHONIOENCODING = 'utf-8'
    & $Python $testScript $Installer
    exit $LASTEXITCODE
}

# Hosted Windows runners are elevated. Exercise the standard-user launch
# required on users' computers, including the SDK's elevation guard.
$username = 'NetDeploySmoke'
$password = ConvertTo-SecureString ('Nda!' + [guid]::NewGuid().ToString('N')) -AsPlainText -Force
$user = New-LocalUser -Name $username -Password $password -PasswordNeverExpires
$output = Join-Path $env:PUBLIC 'NetDeploySmoke'
New-Item -ItemType Directory -Path $output -Force | Out-Null
& icacls.exe $output /grant ('{0}\{1}:(OI)(CI)M' -f $env:COMPUTERNAME,$username) | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare smoke-test directory' }
Start-Service seclogon
try {
    $credential = [PSCredential]::new(('{0}\{1}' -f $env:COMPUTERNAME,$username), $password)
    $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'),
                   '-Installer',('"' + $Installer + '"'),'-Python',('"' + $Python + '"'),'-Child')
    $start = @{
        FilePath = 'powershell.exe'
        ArgumentList = $arguments
        Credential = $credential
        LoadUserProfile = $true
        WindowStyle = 'Hidden'
        WorkingDirectory = $output
        RedirectStandardOutput = (Join-Path $output 'stdout.log')
        RedirectStandardError = (Join-Path $output 'stderr.log')
        Wait = $true
        PassThru = $true
    }
    $process = Start-Process @start
    Get-Content (Join-Path $output 'stdout.log') -Encoding UTF8
    Get-Content (Join-Path $output 'stderr.log') -Encoding UTF8
    if ($process.ExitCode -ne 0) { throw "Installed application test failed ($($process.ExitCode))" }
} finally {
    Remove-LocalUser -Name $username
}
