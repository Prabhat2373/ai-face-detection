; Inno Setup Script for Otence Intelligence Windows Installer
; To compile: Download Inno Setup (https://jrsoftware.org/isdl.php) and run:
; "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging/installer.iss

#define MyAppName "Otence Intelligence"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Otence"
#define MyAppURL "https://otence.com"
#define MyAppExeName "Otence Intelligence.exe"

[Setup]
AppId={{D37E8F19-54B4-4B2E-893C-E8B1A2C3D4E5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=Otence_Intelligence_Setup_v1.0.0
OutputDir=..\dist
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\resources\icon.ico
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Otence Intelligence\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
