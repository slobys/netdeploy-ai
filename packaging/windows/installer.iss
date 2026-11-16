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
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\NetDeploy AI"; Filename: "{app}\NetDeployAI.exe"
Name: "{autoprograms}\{cm:ExitApp}"; Filename: "{app}\NetDeployAI.exe"; Parameters: "--stop"
Name: "{autodesktop}\NetDeploy AI"; Filename: "{app}\NetDeployAI.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NetDeployAI.exe"; Description: "{cm:OpenApp}"; Flags: nowait postinstall skipifsilent

[Code]
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
begin
  Result := '';
  if not StopPanel then
    Result := 'Please finish deployment tasks and exit NetDeploy AI before updating.';
end;

function InitializeUninstall: Boolean;
begin
  Result := StopPanel;
  if not Result then
    MsgBox('Please finish deployment tasks and exit NetDeploy AI first.', mbError, MB_OK);
end;
