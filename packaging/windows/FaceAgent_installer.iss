; FaceAgent Inno Setup installer script
; Template for creating a Windows installer with:
; - Program files copied to {pf}\FaceAgent (changeable to per-user)
; - Start Menu and Desktop shortcuts
; - Optional prompt to specify a vendor license file path (copied to %APPDATA%\FaceAgent\license.key)
; - Runs a PowerShell helper as the interactive user to copy per-user data (DB/models) into %APPDATA%\FaceAgent
; - Uninstall entry registration (handled by Inno Setup)
;
; Before compiling:
; - Replace {#MyAppExeName} if your executable has a different name
; - Update Source paths under [Files] to point to your PyInstaller dist folder (dist\FaceAgent\*)
; - Replace AppId with a stable GUID
; - Adjust AppVersion/AppPublisher and icons
;
; Compile with Inno Setup Compiler (ISCC) or via the Inno Setup IDE.

#define MyAppName "FaceAgent"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "FaceAgent, Inc."
#define MyAppExeName "FaceAgent.exe"    ; name of the executable produced by PyInstaller

[Setup]
AppId={{00000000-0000-0000-0000-000000000000}}  ; <---- REPLACE with your unique GUID
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Default install folder (machine-wide). For per-user installs, use {userappdata}\FaceAgent
DefaultDirName={pf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputBaseFilename=FaceAgentInstaller
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
; If you want per-user install (no admin), set:
; PrivilegesRequired=lowest
; DefaultDirName={userappdata}\{#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; NOTE: Update the Source path to the folder produced by PyInstaller (dist\FaceAgent).
; This copies all files from the dist folder into the installation directory.
Source: "..\..\dist\FaceAgent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

; Include the PowerShell helper which will copy per-user data into %APPDATA%\FaceAgent
Source: "..\..\packaging\windows\copy_initial_data.ps1"; DestDir: "{app}"; Flags: ignoreversion

; Optionally include a default license token in the installer payload (if you ship one)
; Source: "..\..\licenses\license.key"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu shortcut
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\resources\icon.ico"
; Desktop shortcut (controlled by task)
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\resources\icon.ico"

[Run]
; Run the PowerShell helper as the interactive user to populate per-user app data.
; It receives parameters: -InstallDir "<installed-app-path>" -TargetDir "<userappdata>\FaceAgent"
Filename: "powershell"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\copy_initial_data.ps1"" -InstallDir ""{app}"" -TargetDir ""{userappdata}\{#MyAppName}"""; Flags: runminimized runascurrentuser; Description: "Copying initial data to user profile..."

; Optionally offer to launch the app after install
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\{#MyAppName}"

; -----------------------
; Installer Pascal Scripting
; -----------------------
; A small wizard page allows users to optionally provide a license file path.
; If provided, the installer copies it into %APPDATA%\FaceAgent\license.key
[Code]
var
  LicensePage: TInputQueryWizardPage;
  LicenseFilePath: String;

procedure InitializeWizard();
begin
  LicensePage := CreateInputQueryPage(wpSelectDir,
    'License file (optional)',
    'Provide a vendor license (optional)',
    'If you have a vendor-provided license token, you can enter the full path here. ' +
    'The installer will copy it to your user application data folder (%APPDATA%) so the app uses it on first run.');
  LicensePage.Add('License file path:', False);
  LicensePage.Values[0] := '';
end;

procedure CurPageChanged(CurPageID: Integer);
var
  SrcPath, DestDir, DestFile: String;
begin
  if CurPageID = wpReady then
  begin
    LicenseFilePath := Trim(LicensePage.Values[0]);
    if LicenseFilePath <> '' then
    begin
      if not FileExists(LicenseFilePath) then
      begin
        MsgBox('The license file you provided was not found. It will be ignored and a trial will be used instead.', mbInformation, MB_OK);
        Exit;
      end;

      DestDir := ExpandConstant('{userappdata}\{#MyAppName}');
      if not DirExists(DestDir) then
      begin
        if not ForceDirectories(DestDir) then
        begin
          MsgBox('Failed to create user application data folder: ' + DestDir + #13#10 + 'The installer will continue but the license file could not be copied.', mbError, MB_OK);
          Exit;
        end;
      end;

      DestFile := DestDir + '\license.key';
      try
        if not FileCopy(LicenseFilePath, DestFile, False) then
        begin
          MsgBox('Failed to copy license file to: ' + DestFile + #13#10 + 'The installer will continue without the license.', mbError, MB_OK);
        end;
      except
        MsgBox('Unexpected error while copying license file. The installer will continue without the license.', mbError, MB_OK);
      end;
    end;
  end;
end;

{ Utility: recursively create directories (like mkdir -p) }
function ForceDirectories(Dir: String): Boolean;
var
  P: String;
begin
  Result := True;
  if Dir = '' then Exit;
  if DirExists(Dir) then Exit;
  P := ExtractFilePath(Dir);
  if (P <> '') and not DirExists(P) then
    Result := ForceDirectories(P);
  if Result then
    Result := CreateDir(Dir);
end;
