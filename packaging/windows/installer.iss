; Inno Setup script for SVMixer.
;
; Produces a single "SVMixer-Setup-<version>.exe" installer wizard from an
; already-built PyInstaller output folder. Run PyInstaller first (see
; SVMixer.spec / BUILD_WINDOWS.md) so dist\SVMixer\SVMixer.exe exists,
; then compile this script with Inno Setup (Tools > Compile, or
; ISCC.exe from the command line).

#define MyAppName "SVMixer"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "SVMixer"
#define MyAppExeName "SVMixer.exe"
#define MyDistDir "..\..\dist\SVMixer"

[Setup]
; Generate your own GUID for a real release (Tools > Generate GUID in the
; Inno Setup IDE) -- this placeholder is fine for local/test builds, but a
; stable AppId is what lets future installer versions upgrade in place
; instead of installing side-by-side.
AppId={{B6C9B6B0-6E4D-4B9E-9C36-1D4B8B6A2F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=SVMixer-Setup-{#MyAppVersion}
SetupIconFile=..\..\app\ui\assets\logo\SV.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
