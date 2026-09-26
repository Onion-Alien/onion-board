; SoundboardSetup.exe: one file a non-technical person double-clicks on a fresh PC.
;
;   - no Python needed: it ships the PyInstaller build (dist\Soundboard)
;   - no admin needed for the app itself (installs per user, like Discord does)
;   - installs the free VB-Cable virtual cable too (downloaded from vb-audio.com,
;     signature-checked by install-vbcable.ps1; Windows asks "Yes" once)
;   - Desktop + Start menu shortcuts, then opens Soundboard, whose Quick setup
;     asks which mic they use and walks them through Discord
;
; Built by build.ps1 (needs Inno Setup 6: winget install JRSoftware.InnoSetup).

#define AppName "Soundboard"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6B0B6E2F-6D63-4C1B-9E0B-5B8E3C2A71D4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Soundboard
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
WizardStyle=modern
WizardSizePercent=110
SetupIconFile=..\soundboard.ico
; Bun the mascot, rendered by make_bunny.py (build.ps1 runs it)
WizardImageFile=wizard-1x.bmp,wizard-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
UninstallDisplayIcon={app}\Soundboard.exe
OutputDir=..\dist
OutputBaseFilename=SoundboardSetup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Messages]
WelcomeLabel1=Let's set up Soundboard
WelcomeLabel2=This puts Soundboard on your PC and adds the free "virtual cable" it needs, so Discord and your games can hear your sounds.%n%nIt takes about a minute. When Windows asks for permission, click Yes.%n%nClick Next to start.
FinishedHeadingLabel=All done!
FinishedLabel=Soundboard is installed. It will open now and ask you a few easy questions (which mic you use, where you listen).%n%nYou can find it later on your Desktop or in the Start menu.

[Files]
Source: "..\dist\Soundboard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Soundboard.exe"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Soundboard.exe"

[Run]
; The cable script exits straight away when a cable is already installed.
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\_internal\install-vbcable.ps1"" -Silent"; \
  StatusMsg: "Installing the virtual cable... click Yes if Windows asks for permission."; \
  Flags: runhidden waituntilterminated
Filename: "{app}\Soundboard.exe"; Description: "Open Soundboard now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Leave %APPDATA%\Soundboard (their sounds and settings) and the cable in place.
