#ifndef AppVersion
  #error AppVersion required
#endif
#ifndef BundleDir
  #error BundleDir required
#endif
#ifndef OutputDir
  #error OutputDir required
#endif

[Setup]
AppId={{979A5951-82AE-49A9-8795-2862BB24B3C7}
AppName=NetDeploy AI
AppVersion={#AppVersion}
AppPublisher=NetDeploy AI
AppPublisherURL=https://github.com/slobys/netdeploy-ai
DefaultDirName={localappdata}\Programs\NetDeploy AI
DefaultGroupName=NetDeploy AI
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=NetDeployAI-{#AppVersion}-Setup-x64
SetupIconFile={#BundleDir}\netdeploy.ico
UninstallDisplayIcon={app}\NetDeployAI.exe
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
Uninstallable=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: checkedonce

[CustomMessages]
english.DesktopIcon=Create a desktop shortcut
chinesesimplified.DesktopIcon=创建桌面快捷方式
english.ExitApp=Exit NetDeploy AI
chinesesimplified.ExitApp=退出 NetDeploy AI
english.OpenApp=Open NetDeploy AI
chinesesimplified.OpenApp=打开 NetDeploy AI

[Files]
Source: "{#BundleDir}\*"; Excludes: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BundleDir}\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\NetDeploy AI"; Filename: "{app}\NetDeployAI.exe"; IconFilename: "{app}\netdeploy.ico"
Name: "{autoprograms}\{cm:ExitApp}"; Filename: "{app}\NetDeployAI.exe"; IconFilename: "{app}\netdeploy.ico"; Parameters: "--stop"
Name: "{autodesktop}\NetDeploy AI"; Filename: "{app}\NetDeployAI.exe"; IconFilename: "{app}\netdeploy.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\NetDeployAI.exe"; Description: "{cm:OpenApp}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedWebView2: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := not ((RegQueryStringValue(HKCU, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM32, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM64, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')));
end;

function StopPanel: Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if FileExists(ExpandConstant('{app}\NetDeployAI.exe')) then
    Result := Exec(ExpandConstant('{app}\NetDeployAI.exe'), '--stop --quiet', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if not StopPanel then begin
    Result := 'Please finish deployment tasks and exit NetDeploy AI before updating.';
    Exit;
  end;
  if NeedWebView2 then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode) or
      ((ResultCode <> 0) and (ResultCode <> 3010)) then
      Result := 'Microsoft WebView2 could not be installed. Check the network connection and try again.';
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := StopPanel;
  if not Result then
    MsgBox('Please finish deployment tasks and exit NetDeploy AI first.', mbError, MB_OK);
end;
