; Inno Setup script: turns dist\Bowers into Bowers-Setup-<version>.exe
; Build: iscc /DAppVersion=1.0.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B3A9F2E-BA0E-4F6B-9C1D-B0E7E5B0A1E1}
AppName=Bowers
AppVersion={#AppVersion}
AppPublisher=Bowers
AppPublisherURL=https://github.com/JBWeb1/Bowie
DefaultDirName={localappdata}\Programs\Bowers
DefaultGroupName=Bowers
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Bowers-Setup-{#AppVersion}
SetupIconFile=..\docks\web\assets\app.ico
UninstallDisplayIcon={app}\Bowers.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "addtopath"; Description: "Add bowers-cli to PATH (use Bowers from a terminal)"; GroupDescription: "Command line:"

[Files]
Source: "..\dist\Bowers\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Bowers"; Filename: "{app}\Bowers.exe"
Name: "{group}\Uninstall Bowers"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Bowers"; Filename: "{app}\Bowers.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
  Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\Bowers.exe"; Description: "Open Bowers"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Dir: string): boolean;
var Path: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Path) then begin Result := True; exit; end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Path) + ';') = 0;
end;
