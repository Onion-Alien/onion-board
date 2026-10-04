; OnionBoardSetup.exe: one file a non-technical person double-clicks on a fresh PC.
;
;   - no Python needed: it ships the PyInstaller build (dist\OnionBoard)
;   - no admin needed for the app itself (installs per user, like Discord does)
;   - a "Your privacy" page (PrivacyPage in [Code], before the checkboxes): in plain
;     words, what the app connects to and when, what the Tor box does, and a link to
;     SECURITY.md#what-the-app-does-on-the-network. Its "Offline mode" box (unticked;
;     ticked already when the app is in Offline mode) runs OnionBoard.exe --set-offline
;     before anything else runs, so the app never goes online, not even on its first
;     start, and unticks the boxes below that download things (they can be ticked
;     again: the installer downloads those, the app stays offline; Tor is skipped,
;     since the app never starts it while offline)
;   - a "Pick what you want" page of checkboxes:
;       * the free VB-Cable virtual cable (downloaded from vb-audio.com,
;         signature-checked by install-vbcable.ps1; Windows asks "Yes" once)
;       * FFmpeg for m4a / aac / video files (via winget; hidden when ffmpeg is
;         already there or winget isn't)
;       * the add-on modules in ..\modules (retro voice effect, live voice-to-speech)
;       * Tor, unticked: the installer doesn't carry it. A ticked box runs
;         OnionBoard.exe --get-tor, which downloads the Tor Project's Expert Bundle
;         (soundboard/torget.py: SHA-256 pinned, the saved proxy used) into
;         %APPDATA%\OnionBoard\tor\bin (Settings > Privacy's "Get Tor" button does
;         the same). A failed download says so and leaves the app working without it
;       * Keep a history of network activity, unticked: runs OnionBoard.exe
;         --keep-netlog (config netlog_keep; soundboard/netlog.py keep())
;       * a Desktop shortcut
;   - then opens Onion Board, whose Quick setup asks which mic they use and walks
;     them through Discord
;
; Silent installs (/VERYSILENT) use each box's default, or the choices from the
; last install. /OFFLINE=1 is the Offline mode box: it also skips the boxes that
; download (VB-Cable, FFmpeg, live voice, Tor) unless /TASKS= or /MERGETASKS= names
; them. Neither the box nor /OFFLINE ever switches Offline mode off: that's in the app.
; Built by build.ps1 (needs Inno Setup 6: winget install JRSoftware.InnoSetup).

#define AppName "Onion Board"
#define AppExeName "OnionBoard"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B0B6E2F-6D63-4C1B-9E0B-5B8E3C2A71D4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Onion Board
AppPublisherURL=https://github.com/Onion-Alien/onion-board
AppSupportURL=https://github.com/Onion-Alien/onion-board/issues
AppUpdatesURL=https://github.com/Onion-Alien/onion-board/releases
AppCopyright=Copyright (C) Onion Board contributors
; Setup's own file details (Properties -> Details): a named, versioned installer rather
; than a blank one, which also helps machine-learning virus scanners that distrust those
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany=Onion Board
VersionInfoDescription={#AppName} Setup
VersionInfoCopyright=Copyright (C) Onion Board contributors
DefaultDirName={localappdata}\Programs\{#AppExeName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
WizardStyle=modern
WizardSizePercent=110
SetupIconFile=..\assets\onionboard.ico
; Bun the mascot, rendered by scripts\make_bunny.py (build.ps1 runs it)
WizardImageFile=wizard-1x.bmp,wizard-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
UninstallDisplayIcon={app}\{#AppExeName}.exe
OutputDir=..\dist
OutputBaseFilename=OnionBoardSetup
; zip, not solid: don't go back to lzma. Microsoft's machine-learning scanner on
; VirusTotal calls most solid-lzma installers of a PyInstaller app
; Trojan:Win32/Wacatac.B!ml whatever is inside them (a false positive, and a dice roll
; per build); the same files zipped scan clean. It makes the installer bigger.
Compression=zip
SolidCompression=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Messages]
WelcomeLabel1=Let's set up Onion Board
WelcomeLabel2=This puts Onion Board on your PC and adds the free "virtual cable" it needs, so Discord and your games can hear your sounds.%n%nOn the next page you can tick any extras you want. When Windows asks for permission, click Yes.%n%nDid Windows or your browser warn you before this opened ("Windows protected your PC", "not commonly downloaded")? That's normal for a free app that isn't code-signed, and you got past it fine. Next time: More info, then Run anyway.%n%nClick Next to start.
WizardSelectTasks=Pick what you want
SelectTasksDesc=Tick the things you'd like. If you're not sure, leave them as they are.
SelectTasksLabel2=The ticked boxes are what most people want. Click Install when you're ready.
FinishedHeadingLabel=All done!
FinishedLabel=Onion Board is installed. It will open now and ask you a few easy questions (which mic you use, where you listen).%n%nYou can find it later on your Desktop or in the Start menu.%n%nPrivacy: no account, ads or tracking. Settings > Privacy & security shows everything the app does online, lets you switch those things off, and can send all of it through a proxy or Tor.
FinishedRestartLabel=Onion Board is installed. To finish setting up the virtual cable, Windows needs to restart your PC.%n%nAfter the restart, open Onion Board from the Start menu and it will pick up where it left off.

[Tasks]
Name: "vbcable"; Description: "The free virtual cable (VB-Cable): lets Discord and games hear your sounds. Needed unless you already have one."; GroupDescription: "Needed"
Name: "ffmpeg"; Description: "Play M4A, AAC and video files (installs the free FFmpeg, about 100 MB)"; GroupDescription: "Extras"; Check: CanOfferFfmpeg
Name: "livevoice"; Description: "Set up live voice-to-speech now: you talk, others hear a text-to-speech voice. Needs Python from python.org; downloads about 300 MB. (You can also do this later from the Voice tab.)"; GroupDescription: "Extras"; Flags: unchecked
Name: "tor"; Description: "Private connection (Tor): hides your address from the sites you search and download from and the radio stations you play. Slower. Downloads Tor from the Tor Project (about 22 MB). It stays off until you pick it in Settings > Privacy & security."; GroupDescription: "Privacy (optional)"; Flags: unchecked
Name: "keepnetlog"; Description: "Keep a history of everything Onion Board connects to, between starts (Settings > Connection > Network activity). Saved on this PC only; without it the list is forgotten when the app closes."; GroupDescription: "Privacy (optional)"; Flags: unchecked
Name: "desktopicon"; Description: "Put an Onion Board shortcut on my Desktop"; GroupDescription: "Shortcuts"

[InstallDelete]
; The Python runtime and libraries from the last version: cleared first so files a
; release no longer ships don't linger (and get loaded) after an update. Nothing of the
; user's lives there: settings, sounds and downloaded add-ons are in %APPDATA%\OnionBoard,
; and {app}\modules (live-voice's own .venv) is left alone.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Includes the add-ons in {app}\modules (build.ps1 copies them in; see soundboard/modules.py).
; live-voice's own .venv is made later, by the "livevoice" task or the Voice tab's button.
Source: "..\dist\OnionBoard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}.exe"; AppUserModelID: "OnionBoard.App"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}.exe"; AppUserModelID: "OnionBoard.App"

[Run]
; Offline mode first: these entries run before CurStepChanged(ssPostInstall), and the
; relaunch below starts the app. AfterInstall checks config.json really says so.
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--set-offline"; \
  StatusMsg: "Switching on Offline mode..."; \
  Check: OfflineChosen; AfterInstall: CheckOffline; Flags: runhidden waituntilterminated
; "Keep a history" before the first start too, so its first connections are kept.
; Unticking the box never switches it off: that's in the app (it deletes the file).
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--keep-netlog"; \
  StatusMsg: "Switching on the network activity history..."; \
  Tasks: keepnetlog; Flags: runhidden waituntilterminated
; The virtual cable is installed from CurStepChanged in [Code], so its exit code can
; ask for a restart.
Filename: "{code:WingetPath}"; \
  Parameters: "install --id Gyan.FFmpeg.Essentials --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements"; \
  StatusMsg: "Adding M4A and video support (FFmpeg)... this can take a minute."; \
  Tasks: ffmpeg; Check: MayDownload('ffmpeg'); Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/c ""{app}\modules\live-voice\install.bat"" --quiet"; \
  WorkingDir: "{app}\modules\live-voice"; \
  StatusMsg: "Setting up live voice-to-speech (downloads about 300 MB, can take a few minutes)..."; \
  Tasks: livevoice; Check: HasPython and MayDownload('livevoice'); Flags: runhidden waituntilterminated
Filename: "{app}\{#AppExeName}.exe"; Description: "Open Onion Board now"; Flags: nowait postinstall skipifsilent
; The app's own updater (soundboard/updates.py) runs this silently with /RELAUNCH=1 after
; closing itself: open it again once the new version is in place.
; Through Explorer, so the app starts with the user's own environment like a
; double-click does: the updater that started setup is a frozen Python app whose
; variables (PyInstaller's _PYI_*, PATH / QT_PLUGIN_PATH into its old _internal)
; setup inherits, and an app started straight from setup with them crashed on
; start (1.3.3 -> 1.4.0: "Importing the numpy C-extensions failed").
Filename: "{win}\explorer.exe"; Parameters: """{app}\{#AppExeName}.exe"""; Flags: nowait; Check: Relaunch

[Registry]
; "Start with Windows" (Settings -> General) writes this value; nothing is created at
; install, but uninstalling removes it so Windows doesn't try to start a removed app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "OnionBoard"; Flags: uninsdeletevalue dontcreatekey

[UninstallDelete]
; made after install: a module's own Python environment and bytecode
Type: filesandordirs; Name: "{app}\modules"

; Uninstalling leaves %APPDATA%\OnionBoard (their sounds and settings, and a downloaded
; Tor in tor\bin) and FFmpeg in place; the cable is offered for removal
; (CurUninstallStepChanged below).

[Code]
const
  PrivacyURL = 'https://github.com/Onion-Alien/onion-board/blob/main/SECURITY.md#what-the-app-does-on-the-network';

var
  PrivacyPage: TWizardPage;
  OfflineBox: TNewCheckBox;
  OfflineApplied: Boolean;     // the download boxes were unticked for Offline mode
  TasksLabelText: String;      // the Pick what you want page's own label

// "net_offline": true in %APPDATA%\OnionBoard\config.json: the app is in Offline mode
// already (a reinstall). A plain text search: json.dumps writes it on one line.
function ConfigIsOffline: Boolean;
var
  Raw: AnsiString;
  S: String;
begin
  Result := False;
  if not LoadStringFromFile(ExpandConstant('{userappdata}\OnionBoard\config.json'), Raw) then
    exit;
  S := String(Raw);
  StringChangeEx(S, ' ', '', True);
  StringChangeEx(S, #9, '', True);
  StringChangeEx(S, #13, '', True);
  StringChangeEx(S, #10, '', True);
  Result := Pos('"net_offline":true', S) > 0;
end;

// The Offline mode box (silent installs: /OFFLINE=1, or the app already offline)
function OfflineChosen: Boolean;
begin
  Result := (OfflineBox <> nil) and OfflineBox.Checked;
end;

// Is `Task` in the comma-separated /<Param>= list on the command line?
function ListedIn(Param, Task: String): Boolean;
var
  List, Item: String;
  I: Integer;
begin
  Result := False;
  List := Lowercase(ExpandConstant('{param:' + Param + '|}')) + ',';
  while List <> '' do
  begin
    I := Pos(',', List);
    Item := Trim(Copy(List, 1, I - 1));
    Delete(List, 1, I);
    if Item = Lowercase(Task) then
    begin
      Result := True;
      exit;
    end;
  end;
end;

// A box that downloads something: may it? Interactive installs do what's ticked (Offline
// mode unticked them, so a tick now is on purpose). A silent one in Offline mode only
// downloads what /TASKS or /MERGETASKS names; Tor never, since an offline app never
// starts it (and --get-tor would refuse anyway).
function MayDownload(Task: String): Boolean;
begin
  Result := WizardIsTaskSelected(Task);
  if not Result or not OfflineChosen then
    exit;
  if Task = 'tor' then
    Result := False
  else if WizardSilent then
    Result := ListedIn('TASKS', Task) or ListedIn('MERGETASKS', Task);
end;

// after --set-offline: is it really in config.json? If not, say so before they open it
procedure CheckOffline;
begin
  if not ConfigIsOffline then
    SuppressibleMsgBox('Offline mode couldn''t be switched on (the settings file couldn''t ' +
      'be written).' + #13#10#13#10 +
      'Onion Board will go online as usual until you switch it on: before using it, open ' +
      'Settings > Privacy & security and turn on Offline mode.',
      mbError, MB_OK, IDOK);
end;

procedure OpenPrivacyLink(Sender: TObject);
var
  Code: Integer;
begin
  ShellExecAsOriginalUser('open', PrivacyURL, '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

// "Your privacy": what the app connects to, in plain words, before the boxes (so they
// know what the Tor box is for when they get to it). Interactive installs only.
procedure InitializeWizard;
var
  Body, Link, Note: TNewStaticText;
  Bullet: String;
begin
  Bullet := '  ' + #$2022 + '  ';
  PrivacyPage := CreateCustomPage(wpWelcome, 'Your privacy',
    'What Onion Board connects to, and when');
  Body := TNewStaticText.Create(PrivacyPage);
  Body.Parent := PrivacyPage.Surface;
  Body.AutoSize := False;
  Body.WordWrap := True;
  Body.Width := PrivacyPage.SurfaceWidth;
  Body.Caption :=
    'No account, no ads, no tracking. On its own, Onion Board only goes online to ' +
    'check for updates, and you can switch that off.' + #13#10#13#10 +
    'Everything else happens only when you use it:' + #13#10 +
    Bullet + 'Searching for sounds and downloading them goes to YouTube, SoundCloud ' +
    'and Myinstants.' + #13#10 +
    Bullet + 'The radio uses Radio Browser (a free list of stations) and the stations ' +
    'you play.' + #13#10 +
    Bullet + 'Add-on modules are optional: skip their boxes on the next page, or ' +
    'remove them later.' + #13#10#13#10 +
    'Like any website, those sites can see your internet address. The "Private ' +
    'connection (Tor)" box on the next page hides it from them. It''s slower, it ' +
    'downloads Tor from the Tor Project, and it stays off until you pick it in ' +
    'Settings > Privacy & security.';
  Body.AdjustHeight;
  Link := TNewStaticText.Create(PrivacyPage);
  Link.Parent := PrivacyPage.Surface;
  Link.Caption := 'See exactly what the app does online';
  Link.Cursor := crHand;
  Link.Font.Color := clHotLight;
  Link.Font.Style := [fsUnderline];
  Link.OnClick := @OpenPrivacyLink;
  Link.Top := Body.Top + Body.Height + ScaleY(12);
  OfflineBox := TNewCheckBox.Create(PrivacyPage);
  OfflineBox.Parent := PrivacyPage.Surface;
  OfflineBox.Top := Link.Top + Link.Height + ScaleY(14);
  OfflineBox.Width := PrivacyPage.SurfaceWidth;
  OfflineBox.Height := ScaleY(17);
  OfflineBox.Caption := 'Offline mode: Onion Board never goes online, from its first start';
  OfflineBox.Checked := (ExpandConstant('{param:OFFLINE|0}') = '1') or ConfigIsOffline;
  Note := TNewStaticText.Create(PrivacyPage);
  Note.Parent := PrivacyPage.Surface;
  Note.AutoSize := False;
  Note.WordWrap := True;
  Note.Left := ScaleX(18);
  Note.Width := PrivacyPage.SurfaceWidth - ScaleX(18);
  Note.Top := OfflineBox.Top + OfflineBox.Height + ScaleY(2);
  Note.Caption := 'No update checks, no searching or downloading. Unticks the boxes on the ' +
    'next page that download things. Switch it off any time in Settings > Privacy & security.';
  Note.AdjustHeight;
  TasksLabelText := WizardForm.SelectTasksLabel.Caption;
end;

// Offline mode ticked: untick the boxes that download (once, so ticking one again
// sticks) and grey out Tor. Unticked again: back to the defaults.
procedure CurPageChanged(CurPageID: Integer);
var
  I: Integer;
begin
  if (CurPageID <> wpSelectTasks) or WizardSilent then
    exit;
  if OfflineChosen and not OfflineApplied then
    WizardSelectTasks('!vbcable,!ffmpeg,!livevoice,!tor')
  else if OfflineApplied and not OfflineChosen then
    WizardSelectTasks('vbcable,ffmpeg');
  OfflineApplied := OfflineChosen;
  for I := 0 to WizardForm.TasksList.Items.Count - 1 do
    if Pos('(Tor)', WizardForm.TasksList.ItemCaption[I]) > 0 then
      WizardForm.TasksList.ItemEnabled[I] := not OfflineChosen;
  if OfflineChosen then
    WizardForm.SelectTasksLabel.Caption := 'Offline mode is on, so the boxes that ' +
      'download things are unticked. Ticking one lets this installer download it; ' +
      'Onion Board itself stays offline.'
  else
    WizardForm.SelectTasksLabel.Caption := TasksLabelText;
end;

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

// /RELAUNCH=1: started by the app's "Restart to update" (see [Run])
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
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

// VB-Audio's own setup program, which the cable install leaves in Program Files; run
// with -u -h it removes the cable. '' = no cable installed.
function CableSetup: String;
begin
  Result := ExpandConstant('{commonpf64}\VB\CABLE\VBCABLE_Setup_x64.exe');
  if not FileExists(Result) then
    Result := ExpandConstant('{commonpf}\VB\CABLE\VBCABLE_Setup.exe');
  if not FileExists(Result) then
    Result := '';
end;

// Run install-vbcable.ps1 with `Args`; its exit code, or -1 if it couldn't start.
function CableScript(Args: String): Integer;
begin
  if not Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' +
              ExpandConstant('{app}\_internal\install-vbcable.ps1') + '" ' + Args,
              '', SW_HIDE, ewWaitUntilTerminated, Result) then
    Result := -1;
end;

procedure InstallCable;
var
  Code: Integer;
  HadCable: Boolean;
begin
  // ask Windows whether the driver is there (2 = not installed): VB-Audio's own
  // uninstaller leaves its setup program in Program Files, so that proves nothing
  HadCable := CableScript('-Check') <> 2;
  WizardForm.StatusLabel.Caption :=
    'Installing the virtual cable... click Yes if Windows asks for permission.';
  Code := CableScript('-Silent');
  CableNeedsRestart := (Code = 3010);
  // remembered for the uninstaller: a cable we put there is offered for removal first
  if (not HadCable) and ((Code = 0) or (Code = 3010)) then
    RegWriteStringValue(HKCU, 'Software\OnionBoard', 'InstalledCable', '1');
  // after that restart, open the app once by itself on the setup guide's cable step
  // (the same per-user RunOnce entry the guide sets; Windows deletes it as it runs)
  if CableNeedsRestart then
    RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\RunOnce',
      'OnionBoardResumeSetup',
      '"' + ExpandConstant('{app}\{#AppExeName}.exe') + '" --resume-setup');
end;

function NeedRestart(): Boolean;
begin
  Result := CableNeedsRestart;
end;

// Uninstall: offer to remove the cable too. The default answer is Yes only when this
// installer put it there (other apps, e.g. Voicemeeter, may use one that was already
// installed). Silent uninstalls leave it alone.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Setup, Mine: String;
  Code, Default: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  Setup := CableSetup;
  Mine := '';
  RegQueryStringValue(HKCU, 'Software\OnionBoard', 'InstalledCable', Mine);
  if (Setup <> '') and not UninstallSilent then
  begin
    if Mine = '1' then Default := MB_DEFBUTTON1 else Default := MB_DEFBUTTON2;
    if MsgBox('Also remove the virtual cable (VB-Cable)?' + #13#10#13#10 +
        'Onion Board used it to send your sounds into Discord and games. Choose No if ' +
        'another program uses it too (Voicemeeter, another soundboard...).' + #13#10#13#10 +
        'Windows will ask for permission, and may want a restart afterwards.',
        mbConfirmation, MB_YESNO or Default) = IDYES then
    begin
      if ShellExec('runas', Setup, '-u -h', '', SW_HIDE, ewWaitUntilTerminated, Code) then
        // its CABLE devices stay listed (not working) until Windows restarts
        MsgBox('The virtual cable has been removed. Restart your PC to finish: until then ' +
          'Windows still lists "CABLE Input" / "CABLE Output".', mbInformation, MB_OK)
      else
        MsgBox('The virtual cable wasn''t removed (permission was refused). You can remove ' +
          'it later from Settings > Apps > Installed apps > VBCABLE.', mbInformation, MB_OK);
    end;
  end;
  RegDeleteValue(HKCU, 'Software\OnionBoard', 'InstalledCable');
  // a restart still pending: don't try to reopen an app that's gone
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\RunOnce',
    'OnionBoardResumeSetup');
  RegDeleteKeyIfEmpty(HKCU, 'Software\OnionBoard');
end;

// The "tor" box: the app downloads Tor itself (OnionBoard.exe --get-tor, the same
// routine as Settings' Get Tor button: checked against its pinned SHA-256, through the
// saved proxy if there is one). Nothing to do when this Tor is already there.
procedure GetTor;
var
  Code: Integer;
begin
  WizardForm.StatusLabel.Caption :=
    'Downloading Tor from the Tor Project (about 22 MB)... this can take a minute.';
  if not Exec(ExpandConstant('{app}\{#AppExeName}.exe'), '--get-tor', '', SW_HIDE,
              ewWaitUntilTerminated, Code) then
    Code := -1;
  if Code <> 0 then
    SuppressibleMsgBox('Tor couldn''t be downloaded, so the private connection isn''t ' +
      'ready yet. Onion Board works fine without it.' + #13#10#13#10 +
      'Where Tor is blocked, downloading it often is too. You can try again any time: ' +
      'Settings > Privacy & security > Connection > Get Tor.',
      mbInformation, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and MayDownload('vbcable') then
    InstallCable;
  if (CurStep = ssPostInstall) and MayDownload('tor') then
    GetTor;
  if (CurStep = ssPostInstall) and MayDownload('livevoice') and not HasPython then
    SuppressibleMsgBox('Live voice-to-speech needs Python, which isn''t on this PC yet.' + #13#10#13#10 +
      'Get it free from python.org (tick "Add python.exe to PATH" while installing it). ' +
      'Then in Onion Board open the Voice tab and press Install.',
      mbInformation, MB_OK, IDOK);
end;
