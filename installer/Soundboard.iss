; SoundboardSetup.exe: one file a non-technical person double-clicks on a fresh PC.
;
;   - no Python needed: it ships the PyInstaller build (dist\Soundboard)
;   - no admin needed for the app itself (installs per user, like Discord does)
;   - a "Pick what you want" page of checkboxes:
;       * the free VB-Cable virtual cable (downloaded from vb-audio.com,
;         signature-checked by install-vbcable.ps1; Windows asks "Yes" once)
;       * FFmpeg for m4a / aac / video files (via winget; hidden when ffmpeg is
;         already there or winget isn't)
;       * the add-on modules in ..\modules (retro voice effect, live voice-to-speech)
;       * a Desktop shortcut
;   - then opens Soundboard, whose Quick setup asks which mic they use and walks
;     them through Discord
;
; Silent installs (/VERYSILENT) use each box's default, or the choices from the
; last install. Built by build.ps1 (needs Inno Setup 6: winget install JRSoftware.InnoSetup).

#define AppName "Soundboard"
#ifndef AppVersion
  #define AppVersion "1.0.0"
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
WelcomeLabel2=This puts Soundboard on your PC and adds the free "virtual cable" it needs, so Discord and your games can hear your sounds.%n%nOn the next page you can tick any extras you want. When Windows asks for permission, click Yes.%n%nClick Next to start.
WizardSelectTasks=Pick what you want
SelectTasksDesc=Tick the things you'd like. If you're not sure, leave them as they are.
SelectTasksLabel2=The ticked boxes are what most people want. Click Install when you're ready.
FinishedHeadingLabel=All done!
FinishedLabel=Soundboard is installed. It will open now and ask you a few easy questions (which mic you use, where you listen).%n%nYou can find it later on your Desktop or in the Start menu.
FinishedRestartLabel=Soundboard is installed. To finish setting up the virtual cable, Windows needs to restart your PC.%n%nAfter the restart, open Soundboard from the Start menu and it will pick up where it left off.

[Tasks]
Name: "vbcable"; Description: "The free virtual cable (VB-Cable): lets Discord and games hear your sounds. Needed unless you already have one."; GroupDescription: "Needed"
Name: "ffmpeg"; Description: "Play M4A, AAC and video files (installs the free FFmpeg, about 100 MB)"; GroupDescription: "Extras"; Check: CanOfferFfmpeg
Name: "livevoice"; Description: "Set up live voice-to-speech now: you talk, others hear a text-to-speech voice. Needs Python from python.org; downloads about 300 MB. (You can also do this later from the Voice tab.)"; GroupDescription: "Extras"; Flags: unchecked
Name: "desktopicon"; Description: "Put a Soundboard shortcut on my Desktop"; GroupDescription: "Shortcuts"

[Files]
; Includes the add-ons in {app}\modules (build.ps1 copies them in; see soundboard/modules.py).
; live-voice's own .venv is made later, by the "livevoice" task or the Voice tab's button.
Source: "..\dist\Soundboard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Soundboard.exe"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Soundboard.exe"

[Run]
; The virtual cable is installed from CurStepChanged in [Code], so its exit code can
; ask for a restart.
Filename: "{code:WingetPath}"; \
  Parameters: "install --id Gyan.FFmpeg.Essentials --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements"; \
  StatusMsg: "Adding M4A and video support (FFmpeg)... this can take a minute."; \
  Tasks: ffmpeg; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/c ""{app}\modules\live-voice\install.bat"" --quiet"; \
  WorkingDir: "{app}\modules\live-voice"; \
  StatusMsg: "Setting up live voice-to-speech (downloads about 300 MB, can take a few minutes)..."; \
  Tasks: livevoice; Check: HasPython; Flags: runhidden waituntilterminated
Filename: "{app}\Soundboard.exe"; Description: "Open Soundboard now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; made after install: a module's own Python environment and bytecode
Type: filesandordirs; Name: "{app}\modules"

; Uninstalling leaves %APPDATA%\Soundboard (their sounds and settings), the cable and
; FFmpeg in place.

[Code]
function WingetPath(Param: String): String;
begin
  Result := ExpandConstant('{localappdata}\Microsoft\WindowsApps\winget.exe');
end;

function HasFfmpeg: Boolean;
begin
  Result := (FileSearch('ffmpeg.exe', GetEnv('PATH')) <> '') or
            FileExists(ExpandConstant('{localappdata}\Microsoft\WinGet\Links\ffmpeg.exe')) or
            FileExists(ExpandConstant('{commonpf64}\WinGet\Links\ffmpeg.exe'));
end;

// Offered only when it's missing and winget (built into Windows 10/11) is there to get it.
function CanOfferFfmpeg: Boolean;
begin
  Result := (not HasFfmpeg) and FileExists(WingetPath(''));
end;

// The python.org install puts the "py" launcher in one of these.
function HasPython: Boolean;
begin
  Result := FileExists(ExpandConstant('{win}\py.exe')) or
            FileExists(ExpandConstant('{localappdata}\Programs\Python\Launcher\py.exe')) or
            RegKeyExists(HKCU, 'Software\Python\PythonCore') or
            RegKeyExists(HKLM, 'Software\Python\PythonCore');
end;

// install-vbcable.ps1 skips a working cable, installs one otherwise, then checks it:
// exit 3010 = installed but Windows needs a restart. VB-Audio recommends one, but it
// often isn't needed, so the Finished page only offers "Restart now / later" when the
// check says so (and /NORESTART keeps silent installs from restarting).
var
  CableNeedsRestart: Boolean;

procedure InstallCable;
var
  Code: Integer;
begin
  WizardForm.StatusLabel.Caption :=
    'Installing the virtual cable... click Yes if Windows asks for permission.';
  if Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' +
          ExpandConstant('{app}\_internal\install-vbcable.ps1') + '" -Silent',
          '', SW_HIDE, ewWaitUntilTerminated, Code) then
    CableNeedsRestart := (Code = 3010);
end;

function NeedRestart(): Boolean;
begin
  Result := CableNeedsRestart;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('vbcable') then
    InstallCable;
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('livevoice') and not HasPython then
    SuppressibleMsgBox('Live voice-to-speech needs Python, which isn''t on this PC yet.' + #13#10#13#10 +
      'Get it free from python.org (tick "Add python.exe to PATH" while installing it). ' +
      'Then in Soundboard open the Voice tab and press Install.',
      mbInformation, MB_OK, IDOK);
end;
