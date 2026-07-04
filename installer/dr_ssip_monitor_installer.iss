; Inno Setup script for packaging the FRAME application as a DR_SSIP_Monitor installer.

#define MyAppName "DR_SSIP_Monitor"
#define MyAppExeName "frame.exe"
#define MyAppCliExeName "frame-cli.exe"
#ifndef MyAppVersion
#define MyAppVersion "1.3.0"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "LWX"
#endif

[Setup]
AppId={{A2C285A5-C0D5-44DB-AE30-7159A0B7E8C1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
UsePreviousAppDir=yes
UsePreviousGroup=yes
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist\installer
OutputBaseFilename=DR_SSIP_Monitor-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName},{#MyAppCliExeName}
RestartApplications=no
SetupLogging=yes
ChangesEnvironment=yes

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional tasks:"; Flags: unchecked

[InstallDelete]
Type: files; Name: "{app}\{#MyAppExeName}"
Type: files; Name: "{app}\{#MyAppCliExeName}"
Type: files; Name: "{app}\frame.bat"
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\frame\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dr_ssip_monitor_brand.txt"; DestDir: "{app}"; DestName: "app_brand.txt"; Flags: ignoreversion
Source: "..\scripts\frame-installed.bat"; DestDir: "{app}"; DestName: "frame.bat"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} Terminal"; Filename: "{cmd}"; Parameters: "/k ""{app}\{#MyAppCliExeName}"""; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  EnvironmentKey = 'Environment';

function PathContainsSegment(PathValue: string; Segment: string): Boolean;
begin
  Result := Pos(';' + Uppercase(Segment) + ';', ';' + Uppercase(PathValue) + ';') > 0;
end;

function RemovePathSegment(PathValue: string; Segment: string): string;
var
  Remaining: string;
  Part: string;
  SeparatorPos: Integer;
begin
  Result := '';
  Remaining := PathValue;
  while Remaining <> '' do
  begin
    SeparatorPos := Pos(';', Remaining);
    if SeparatorPos > 0 then
    begin
      Part := Copy(Remaining, 1, SeparatorPos - 1);
      Delete(Remaining, 1, SeparatorPos);
    end
    else
    begin
      Part := Remaining;
      Remaining := '';
    end;

    if (Part <> '') and (Uppercase(Part) <> Uppercase(Segment)) then
    begin
      if Result = '' then
        Result := Part
      else
        Result := Result + ';' + Part;
    end;
  end;
end;

procedure AddInstallDirToUserPath;
var
  PathValue: string;
  AppDir: string;
begin
  AppDir := ExpandConstant('{app}');
  if not RegQueryStringValue(HKCU, EnvironmentKey, 'Path', PathValue) then
    PathValue := '';
  if not PathContainsSegment(PathValue, AppDir) then
  begin
    if PathValue = '' then
      PathValue := AppDir
    else
      PathValue := PathValue + ';' + AppDir;
    RegWriteStringValue(HKCU, EnvironmentKey, 'Path', PathValue);
  end;
end;

procedure RemoveInstallDirFromUserPath;
var
  PathValue: string;
  NewPathValue: string;
  AppDir: string;
begin
  AppDir := ExpandConstant('{app}');
  if RegQueryStringValue(HKCU, EnvironmentKey, 'Path', PathValue) then
  begin
    NewPathValue := RemovePathSegment(PathValue, AppDir);
    if NewPathValue <> PathValue then
      RegWriteStringValue(HKCU, EnvironmentKey, 'Path', NewPathValue);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    AddInstallDirToUserPath;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveInstallDirFromUserPath;
end;
