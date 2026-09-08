#define MyAppName "FRAME"
#ifndef MyAppVersion
  #error MyAppVersion is required
#endif
#ifndef PackageDir
  #error PackageDir is required
#endif
[Setup]
AppId={{6E1E04A9-84D7-46FD-9379-9EFD1D5BE8E2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName=FRAME {#MyAppVersion}
AppPublisher=LWX
DefaultDirName={localappdata}\Programs\FRAME
DefaultGroupName=FRAME
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=FRAME-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
SetupIconFile=..\assets\frame_icon.ico
UninstallDisplayIcon={app}\Frame.Desktop.exe
CloseApplications=yes
CloseApplicationsFilter=Frame.Desktop.exe,frame.exe,frame-cli.exe
RestartApplications=no
ChangesEnvironment=yes
Uninstallable=not IsValidationInstall
SetupLogging=yes
[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[InstallDelete]
Type: files; Name: "{app}\frame-cli.exe"
Type: filesandordirs; Name: "{app}\_internal"
[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\FRAME"; Filename: "{app}\Frame.Desktop.exe"; Check: not IsValidationInstall
Name: "{group}\FRAME Terminal"; Filename: "{cmd}"; Parameters: "/k ""{app}\frame.exe"" shell"; Check: not IsValidationInstall
Name: "{autodesktop}\FRAME"; Filename: "{app}\Frame.Desktop.exe"; Tasks: desktopicon; Check: not IsValidationInstall
[Run]
Filename: "{app}\Frame.Desktop.exe"; Description: "Launch FRAME"; Flags: nowait postinstall skipifsilent; Check: not IsValidationInstall
[Code]
function IsValidationInstall: Boolean;
begin
  Result := ExpandConstant('{param:FRAMEVALIDATE|0}') = '1';
end;
function RemovePathSegment(Value, Segment: string): string;
var Part: string; P: Integer;
begin
  Result := '';
  while Value <> '' do begin
    P := Pos(';', Value);
    if P = 0 then begin Part := Value; Value := ''; end
    else begin Part := Copy(Value, 1, P - 1); Delete(Value, 1, P); end;
    if (Part <> '') and (CompareText(Part, Segment) <> 0) then begin
      if Result <> '' then Result := Result + ';';
      Result := Result + Part;
    end;
  end;
end;
procedure CurStepChanged(CurStep: TSetupStep);
var Value, AppDir: string;
begin
  if (CurStep = ssPostInstall) and not IsValidationInstall then begin
    AppDir := ExpandConstant('{app}');
    RegQueryStringValue(HKCU, 'Environment', 'Path', Value);
    if Pos(';' + Uppercase(AppDir) + ';', ';' + Uppercase(Value) + ';') = 0 then begin
      if Value <> '' then Value := Value + ';';
      RegWriteStringValue(HKCU, 'Environment', 'Path', Value + AppDir);
    end;
  end;
end;
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Value: string;
begin
  if CurUninstallStep = usUninstall then
    if RegQueryStringValue(HKCU, 'Environment', 'Path', Value) then
      RegWriteStringValue(HKCU, 'Environment', 'Path', RemovePathSegment(Value, ExpandConstant('{app}')));
end;
