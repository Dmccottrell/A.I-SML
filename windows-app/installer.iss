; The Emvryx installer for Windows (Inno Setup, free): installs for this person only (no admin prompt), adds Emvryx to the Start menu and,
; if they tick it, the desktop and Windows start-up. An update installs over the old one. Built by .github/workflows/windows-app.yml.
#define AppVersion GetEnv("EMVRYX_VERSION")
#if AppVersion == ""
  #define AppVersion "1.0"
#endif

[Setup]
AppId={{8F3E6A2C-4B1D-4E7A-9C55-0E2B7D3A91F4}
AppName=Emvryx
AppVersion={#AppVersion}
AppPublisher=Emvryx
DefaultDirName={localappdata}\Programs\Emvryx
DefaultGroupName=Emvryx
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Emvryx-Setup
SetupIconFile=emvryx.ico
UninstallDisplayIcon={app}\Emvryx.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put Emvryx on the desktop"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Open Emvryx when Windows starts"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\build\Release\Emvryx.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Emvryx"; Filename: "{app}\Emvryx.exe"
Name: "{userdesktop}\Emvryx"; Filename: "{app}\Emvryx.exe"; Tasks: desktopicon
Name: "{userstartup}\Emvryx"; Filename: "{app}\Emvryx.exe"; Tasks: startup

[Run]
Filename: "{app}\Emvryx.exe"; Description: "Open Emvryx now"; Flags: nowait postinstall skipifsilent
