; Windows installer for My Data Center (built by the cloud workflow with Inno Setup 6)
#define AppVer GetEnv("APP_VERSION")
#if AppVer == ""
  #define AppVer "0.2.0"
#endif

[Setup]
AppId={{8C3F2A51-6D7E-4B1A-9F0C-3E5D7A2B9C41}
AppName=My Data Center
AppVersion={#AppVer}
AppPublisher=My Data Center
AppVerName=My Data Center {#AppVer}
DefaultDirName={localappdata}\Programs\My Data Center
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=MyDataCenter-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\My Data Center.exe
UninstallDisplayName=My Data Center
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the desktop"

[Files]
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: VCRedistNeeded
Source: "..\dist\My Data Center\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\My Data Center"; Filename: "{app}\My Data Center.exe"
Name: "{autodesktop}\My Data Center"; Filename: "{app}\My Data Center.exe"; Tasks: desktopicon

[Run]
; Microsoft Visual C++ Runtime: the AI engine needs it and fresh Windows installs don't have it
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ Runtime..."; Flags: shellexec waituntilterminated; Verb: "runas"; Check: VCRedistNeeded
Filename: "{app}\My Data Center.exe"; Description: "Open My Data Center now"; Flags: nowait postinstall skipifsilent
; after an in-app update (silent install), reopen the app automatically
Filename: "{app}\My Data Center.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /t /im ""My Data Center.exe"""; Flags: runhidden; RunOnceId: "StopApp"

[Code]
function VCRedistNeeded: Boolean;
var
  Installed: Cardinal;
begin
  Result := not (RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1));
end;
