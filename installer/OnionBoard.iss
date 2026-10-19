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
;       * the free VB-Cable virtual cable, unticked: sounds go straight into the mic
;         by default (soundboard/mic/directmic.py, set up by the app's Quick setup), and
;         the cable is only the fallback way (downloaded from vb-audio.com,
;         signature-checked by install-vbcable.ps1; Windows asks "Yes" once)
;       * FFmpeg for m4a / aac / video files (via winget; hidden when ffmpeg is
;         already there or winget isn't)
;       * live voice-to-speech's set-up (its module itself always ships, like the
;         other add-on modules in ..\modules but ai-voices): OnionBoard.exe
;         --install-addon live-voice, which gets the add-on a Python of its own
;         (soundboard/online/pyget.py) when the PC has no good one
;       * Tor, unticked: the installer doesn't carry it. A ticked box runs
;         OnionBoard.exe --get-tor, which downloads the Tor Project's Expert Bundle
;         (soundboard/online/torget.py: SHA-256 pinned, the saved proxy used) into
;         %APPDATA%\OnionBoard\tor\bin (Settings > Connection's "Get Tor" button does
;         the same). A failed download says so and leaves the app working without it
;       * Keep a history of network activity, unticked: runs OnionBoard.exe
;         --keep-netlog (config netlog_keep; soundboard/online/netlog.py keep())
;       * a Desktop shortcut
;   - a "Bring your sounds over" page (ImportPage in [Code]), only when another
;     soundboard's board is on this PC: Soundpad's %APPDATA%\Leppsoft\soundlist.spl,
;     Resanance's %APPDATA%\Resanance\data\Resanance.db, Soundux's
;     %APPDATA%\Soundux\config.json, EXP Soundboard's last board in the registry
;     (soundboard/otherboards/__init__.py). The last page before installing: a ticked box per
;     app found. Ticked ones are written to %APPDATA%\OnionBoard\import-from and the
;     app's first start copies the sounds in. Silent installs only do it for the apps
;     /IMPORT= names (comma-separated keys: soundpad,resanance,soundux,expboard):
;     nobody saw the boxes
;   - then opens Onion Board, whose Quick setup asks which mic they use, puts the
;     sounds straight into it (Windows asks "Yes" once) and walks them through Discord
;
; Silent installs (/VERYSILENT) use each box's default, or the choices from the
; last install. /OFFLINE=1 is the Offline mode box: it also skips the boxes that
; download (VB-Cable, FFmpeg, live voice, Tor) unless /TASKS= or /MERGETASKS= names
; them. Neither the box nor /OFFLINE ever switches Offline mode off: that's in the app.
; Compiled with /DPREVIEW it's a look at the import page only, for screenshots: every
; other page is skipped, all four apps are offered, and it can't install.
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
AppPublisher=Onion Alien
AppPublisherURL=https://github.com/Onion-Alien/onion-board
AppSupportURL=https://github.com/Onion-Alien/onion-board/issues
AppUpdatesURL=https://github.com/Onion-Alien/onion-board/releases
AppCopyright=Copyright (C) Onion Board contributors
; Shown in Windows' installed-apps details (Comments / Contact)
AppComments=A free soundboard: plays sounds through your mic into Discord and games
AppContact=https://github.com/Onion-Alien/onion-board/issues
; Setup's own file details (Properties -> Details): a named, versioned installer rather
; than a blank one, which also helps machine-learning virus scanners that distrust those
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany=Onion Alien
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
WizardSizePercent=110,100
SetupIconFile=..\assets\onionboard.ico
; Bun the mascot, rendered by scripts\pictures\make_bunny.py (build.ps1 runs it)
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
WelcomeLabel2=Onion Board plays your sounds straight into your mic, so Discord and your games hear them. Nothing to set up in those apps.%n%nClick Next to start.
WizardSelectTasks=Pick what you want
SelectTasksDesc=Tick what you'd like. If you're not sure, leave the boxes as they are.
FinishedHeadingLabel=All done!
FinishedLabel=Onion Board is installed. It will open now and ask you a few easy questions (which mic you use, where you listen), then put your sounds straight into that mic.%n%nYou can find it later on your Desktop or in the Start menu.%n%nPrivacy: no account or ads. If you left Count me in ticked, it sends anonymous usage stats once a day (never your name, IP address or device info). Settings > Privacy & security shows everything the app does online, lets you switch those things off, and can send all of it through a proxy or Tor.
FinishedRestartLabel=Onion Board is installed. To finish setting up the virtual cable, Windows needs to restart your PC.%n%nAfter the restart, open Onion Board from the Start menu and it will pick up where it left off.

[Tasks]
Name: "ffmpeg"; Description: "Play M4A, AAC and video files (the free FFmpeg, about 100 MB)"; Check: CanOfferFfmpeg
Name: "livevoice"; Description: "Live voice-to-speech (about 300 MB)"; Flags: unchecked
Name: "tor"; Description: "Hide my internet address (Tor), about 22 MB"; Flags: unchecked
Name: "countme"; Description: "Count me in: anonymous usage stats (features used, crash counts)"
Name: "desktopicon"; Description: "Put an Onion Board shortcut on my Desktop"
Name: "vbcable"; Description: "The free virtual cable (VB-Cable): only if you know you need one"; GroupDescription: "Advanced (most people can skip this)"; Flags: unchecked; Check: not CableInstalled

[InstallDelete]
; The Python runtime and libraries from the last version: cleared first so files a
; release no longer ships don't linger (and get loaded) after an update. Nothing of the
; user's lives there: settings, sounds and downloaded add-ons are in %APPDATA%\OnionBoard,
; and {app}\modules (live-voice's own .venv, and its .python when it got one) is left alone.
Type: filesandordirs; Name: "{app}\_internal"
; the exe a past update moved aside (MoveOldExeAside), if it was still running then
Type: files; Name: "{app}\{#AppExeName}.exe.old*"

[Files]
; Includes the add-ons in {app}\modules (build.ps1 copies them in; see soundboard/addons/modules.py).
; live-voice's own .venv is made later, by the "livevoice" task or the Voice tab's button.
#ifndef PREVIEW
; In this order, for an app started while the files are replaced (a double-click during
; an update): first Python itself (the .dll / .pyd files at the top of _internal and
; base_library.zip), so a start gets past the launcher and Python's start-up hooks to
; main.py's check (soundboard/core/installmark.py) and quits quietly; then the rest;
; OnionBoard.exe last, after closing any copy running from {app} and moving the old exe
; aside (MoveOldExeAside). A copy stuck on the launcher's error box kept the exe open: the
; silent update gave up (Abort) and rolled back, leaving no _internal and an app that
; wouldn't start. Windows lets a running program's file be renamed, never replaced.
Source: "..\dist\OnionBoard\_internal\*.dll"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\dist\OnionBoard\_internal\*.pyd"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\dist\OnionBoard\_internal\base_library.zip"; DestDir: "{app}\_internal"; Flags: ignoreversion
; Files with the same bytes as another (mostly the mic helper's own copy of Python) are
; stored once: scripts\buildtools\installer_dupes.py gives each copy an entry of its own naming the
; file kept, which MergeDuplicateFiles stores once, and lists it in DupExcludes for the
; entry below to skip. Every file still lands where it was. build.ps1 writes the list.
#include "..\build\installer\dupes.iss"
Source: "..\dist\OnionBoard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "\{#AppExeName}.exe,\_internal\*.dll,\_internal\*.pyd,\_internal\base_library.zip{#DupExcludes}"
Source: "..\dist\OnionBoard\{#AppExeName}.exe"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: MoveOldExeAside
#endif
; The cable step runs first, before the files above are copied (see CurStepChanged), so it
; needs its own copy of the script to extract into {tmp}.
Source: "install-vbcable.ps1"; Flags: dontcopy

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}.exe"; AppUserModelID: "OnionBoard.App"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}.exe"; AppUserModelID: "OnionBoard.App"

[Run]
; Offline mode first: these entries run before CurStepChanged(ssPostInstall), and the
; relaunch below starts the app. AfterInstall checks config.json really says so.
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--set-offline"; \
  StatusMsg: "Switching on Offline mode..."; \
  Check: OfflineChosen; AfterInstall: CheckOffline; Flags: runhidden waituntilterminated
; "Keep a history" (/KEEPNETLOG=1; the box is in the app's Settings) before the first
; start too, so its first connections are kept.
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--keep-netlog"; \
  StatusMsg: "Switching on the network activity history..."; \
  Check: KeepNetlogParam; Flags: runhidden waituntilterminated
; "Count me in" (soundboard/core/usage.py): unticked, it's switched off before the first
; start; the only thing ever sent is one anonymous "opt-out/installer" (no ID). Ticked on a page the user saw, it's switched on (an
; old install had it off); a silent update never switches it on.
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--usage-count off"; \
  StatusMsg: "Nearly done..."; \
  Tasks: not countme; Flags: runhidden waituntilterminated
; It also passes on the last page's "Where did you hear about Onion Board?".
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--usage-count on{code:HeardArg}"; \
  StatusMsg: "Nearly done..."; \
  Tasks: countme; Check: not WizardSilent; Flags: runhidden waituntilterminated
; The virtual cable is installed from CurStepChanged in [Code], so its exit code can
; ask for a restart.
; FFmpeg, live voice and Tor download from CurStepChanged in [Code] (RunExtra), so the
; window keeps working and Cancel can stop them.
Filename: "{app}\{#AppExeName}.exe"; Description: "Open Onion Board now"; Flags: nowait postinstall skipifsilent; BeforeInstall: EndInstallingMark
; The app's own updater (soundboard/core/updates.py) runs this silently with /RELAUNCH=1 after
; closing itself: open it again once the new version is in place.
; Through Explorer, so the app starts with the user's own environment like a
; double-click does: the updater that started setup is a frozen Python app whose
; variables (PyInstaller's _PYI_*, PATH / QT_PLUGIN_PATH into its old _internal)
; setup inherits, and an app started straight from setup with them crashed on
; start (1.3.3 -> 1.4.0: "Importing the numpy C-extensions failed").
Filename: "{win}\explorer.exe"; Parameters: """{app}\{#AppExeName}.exe"""; Flags: nowait; Check: Relaunch; BeforeInstall: EndInstallingMark

[UninstallRun]
; Straight into my mic: take Onion Board off the mic first, so every mic is exactly as
; it was. Windows asks for permission once, and only if it's on a mic at all.
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--direct-mic remove"; \
  RunOnceId: "DirectMicRemove"; Flags: runhidden waituntilterminated

[Registry]
; "Start with Windows" (Settings -> General) writes this value; nothing is created at
; install, but uninstalling removes it so Windows doesn't try to start a removed app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "OnionBoard"; Flags: uninsdeletevalue dontcreatekey

[UninstallDelete]
; the exe an update moved aside (MoveOldExeAside)
Type: files; Name: "{app}\{#AppExeName}.exe.old*"
; made after install: a module's own Python environment and bytecode
Type: filesandordirs; Name: "{app}\modules"

; Uninstalling leaves %APPDATA%\OnionBoard (their sounds and settings, and a downloaded
; Tor in tor\bin) and FFmpeg in place; the cable is offered for removal
; (CurUninstallStepChanged below).

[Code]
const
  PrivacyURL = 'https://github.com/Onion-Alien/onion-board/blob/main/SECURITY.md#what-the-app-does-on-the-network';
  UninstallFeedbackURL = 'https://tally.so/r/rjxjyM';   // feedback.py's FORM_URL
  DiscordURL = 'https://discord.gg/FhKGaWCWHM';          // feedback.py's DISCORD_URL

var
  PrivacyPage: TWizardPage;
  OfflineBox: TNewCheckBox;
  OfflineApplied: Boolean;     // the download boxes were unticked for Offline mode
  PagesBottom: Integer;        // where the pages end (LayoutHeader keeps it)
  BunnyRight: Integer;         // the bunny's right edge in the header
  CableUnticked: Boolean;      // the cable box was unticked on the first visit
  Bunny: TBitmapImage;
  TorCaption: String;          // the Tor box's own caption (Offline mode replaces it)
  CableKnown, CableThere: Boolean;   // CableInstalled's answer, asked once
  ImportPage: TWizardPage;     // "Bring your sounds over": only when one is found
  ImportBoxes: array of TNewCheckBox;
  ImportKeys: array of String; // soundboard/otherboards/__init__.py's key for each box
  ImportTop: Integer;          // where the next box goes
  HeardPage: TWizardPage;      // "Where did you hear about Onion Board?": new installs
  HeardRadios: array of TNewRadioButton;
  HeardKeys: array of String;  // what each one sends (soundboard/core/usage.py's HEARD)
  HeardOther: TNewEdit;        // Other's own answer
  DiscordLink: TNewStaticText; // the Finished page's "Join the Onion Board Discord"

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

// A working VB-Cable already on this PC: an active playback device whose driver is
// "VB-Audio Virtual Cable" (Windows' own list of sound devices, read-only)
function CableInstalled: Boolean;
var
  Root, I: Integer;
  Base: String;
  Keys: TArrayOfString;
  State: Cardinal;
  Driver: String;
begin
  if CableKnown then
  begin
    Result := CableThere;
    exit;
  end;
  CableKnown := True;
  CableThere := False;
  if IsWin64 then Root := HKLM64 else Root := HKLM;
  Base := 'SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render';
  if RegGetSubkeyNames(Root, Base, Keys) then
    for I := 0 to GetArrayLength(Keys) - 1 do
      if RegQueryDWordValue(Root, Base + '\' + Keys[I], 'DeviceState', State) and
         (State = 1) and
         RegQueryStringValue(Root, Base + '\' + Keys[I] + '\Properties',
           '{b3f8fa53-0004-438e-9003-51a46e139bfc},6', Driver) and
         (Pos('VB-Audio Virtual Cable', Driver) > 0) then
      begin
        CableThere := True;
        break;
      end;
  Result := CableThere;
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

// Only when clicked: the Finished page never opens it by itself
procedure OpenDiscordLink(Sender: TObject);
var
  Code: Integer;
begin
  ShellExecAsOriginalUser('open', DiscordURL, '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

// The Finished page's link, under whatever is last there (the "Open Onion Board now"
// box, or the restart choice): placed when the page shows, once those are laid out.
procedure CreateDiscordLink;
begin
  DiscordLink := TNewStaticText.Create(WizardForm.FinishedPage);
  DiscordLink.Parent := WizardForm.FinishedPage;
  DiscordLink.Caption := 'Join the Onion Board Discord';
  DiscordLink.Hint := 'Chat, get help and hear about new versions (opens in your browser)';
  DiscordLink.ShowHint := True;
  DiscordLink.Cursor := crHand;
  DiscordLink.Font.Color := clHotLight;
  DiscordLink.Font.Style := [fsUnderline];
  DiscordLink.OnClick := @OpenDiscordLink;
end;

procedure PlaceDiscordLink;
var
  Bottom: Integer;
begin
  Bottom := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height;
  if WizardForm.RunList.Visible then
    Bottom := WizardForm.RunList.Top + WizardForm.RunList.Height;
  if WizardForm.NoRadio.Visible then
    Bottom := WizardForm.NoRadio.Top + WizardForm.NoRadio.Height;
  DiscordLink.Left := WizardForm.FinishedLabel.Left;
  DiscordLink.Top := Bottom + ScaleY(12);
end;

// "Your privacy": what the app connects to, in plain words, before the boxes (so they
// know what the Tor box is for when they get to it). Interactive installs only.
function HasSoundpad: Boolean;
begin
  Result := FileExists(ExpandConstant('{userappdata}\Leppsoft\soundlist.spl'));
end;

function HasResanance: Boolean;
begin
  Result := FileExists(ExpandConstant('{userappdata}\Resanance\data\Resanance.db'));
end;

function HasSoundux: Boolean;
begin
  Result := FileExists(ExpandConstant('{userappdata}\Soundux\config.json'));
end;

// EXP Soundboard remembers its last board in Java's Preferences (soundboard/otherboards/expboard.py)
function HasExpBoard: Boolean;
begin
  Result := RegValueExists(HKCU, 'Software\JavaSoft\Prefs\/Expenosa''s /Soundboard',
    'last/Soundboard/Used');
end;

// One app's box on the import page, with what comes over under it
procedure AddImportBox(Key, AppName, What: String);
var
  Box: TNewCheckBox;
  Note: TNewStaticText;
  I: Integer;
begin
  I := GetArrayLength(ImportBoxes);
  SetArrayLength(ImportBoxes, I + 1);
  SetArrayLength(ImportKeys, I + 1);
  Box := TNewCheckBox.Create(ImportPage);
  Box.Parent := ImportPage.Surface;
  Box.Top := ImportTop;
  Box.Width := ImportPage.SurfaceWidth;
  Box.Height := ScaleY(17);
  Box.Caption := 'Bring my sounds over from ' + AppName;
  Box.Checked := True;
  Note := TNewStaticText.Create(ImportPage);
  Note.Parent := ImportPage.Surface;
  Note.AutoSize := False;
  Note.WordWrap := True;
  Note.Left := ScaleX(18);
  Note.Width := ImportPage.SurfaceWidth - ScaleX(18);
  Note.Top := Box.Top + Box.Height + ScaleY(2);
  Note.ShowAccelChar := False;
  Note.Caption := What;
  Note.AdjustHeight;
  ImportTop := Note.Top + Note.Height + ScaleY(8);
  ImportBoxes[I] := Box;
  ImportKeys[I] := Key;
end;

// The page before installing, when another soundboard is on this PC: a ticked box
// for each one found. Skipped (ShouldSkipPage) when none is.
procedure CreateImportPage;
var
  Body, Later: TNewStaticText;
  Preview: Boolean;
begin
#ifdef PREVIEW
  Preview := True;
#else
  Preview := False;
#endif
  ImportPage := CreateCustomPage(wpSelectTasks, 'Bring your sounds over',
    'Found another soundboard on this PC');
  Body := TNewStaticText.Create(ImportPage);
  Body.Parent := ImportPage.Surface;
  Body.AutoSize := False;
  Body.WordWrap := True;
  Body.Width := ImportPage.SurfaceWidth;
  Body.ShowAccelChar := False;
  Body.Caption := 'Onion Board can copy your sounds in from it the first time it opens, ' +
    'so your board is ready straight away. Your other app isn''t touched.';
  Body.AdjustHeight;
  ImportTop := Body.Top + Body.Height + ScaleY(12);
  if Preview or HasSoundpad then
    AddImportBox('soundpad', 'Soundpad', 'With their names, categories and hotkeys.');
  if Preview or HasResanance then
    AddImportBox('resanance', 'Resanance', 'With their names, tabs and hotkeys.');
  if Preview or HasSoundux then
    AddImportBox('soundux', 'Soundux', 'With their names, tabs and hotkeys.');
  if Preview or HasExpBoard then
    AddImportBox('expboard', 'EXP Soundboard',
      'With their hotkeys. EXP Soundboard doesn''t keep names, so each takes its file''s name.');
  Later := TNewStaticText.Create(ImportPage);
  Later.Parent := ImportPage.Surface;
  Later.AutoSize := False;
  Later.WordWrap := True;
  Later.Width := ImportPage.SurfaceWidth;
  Later.Top := ImportTop + ScaleY(4);
  Later.ShowAccelChar := False;
  Later.Caption := 'Rather do it later? In Onion Board: Backup > Import from another soundboard.';
  Later.AdjustHeight;
end;

procedure HeardOtherTyped(Sender: TObject);
begin
  if HeardOther.Text <> '' then
    HeardRadios[GetArrayLength(HeardRadios) - 2].Checked := True;   // Other
end;

procedure AddHeardRadio(Key, Caption: String; var Top: Integer);
var
  I: Integer;
  R: TNewRadioButton;
begin
  I := GetArrayLength(HeardRadios);
  SetArrayLength(HeardRadios, I + 1);
  SetArrayLength(HeardKeys, I + 1);
  R := TNewRadioButton.Create(HeardPage);
  R.Parent := HeardPage.Surface;
  R.Top := Top;
  R.Width := HeardPage.SurfaceWidth;
  R.Height := ScaleY(17);
  R.Caption := Caption;
  HeardRadios[I] := R;
  HeardKeys[I] := Key;
  Top := Top + ScaleY(23);
end;

// The last page of a new install with Count me in ticked: where they heard about the
// app, sent once with the first-start count (soundboard/core/usage.py heard_tag, which
// drops a typed answer that doesn't look like a name). "Rather not say" is picked.
procedure CreateHeardPage;
var
  Body: TNewStaticText;
  Top: Integer;
begin
  HeardPage := CreateCustomPage(ImportPage.ID, 'One last thing',
    'Where did you hear about Onion Board?');
  Body := TNewStaticText.Create(HeardPage);
  Body.Parent := HeardPage.Surface;
  Body.AutoSize := False;
  Body.WordWrap := True;
  Body.Width := HeardPage.SurfaceWidth;
  Body.ShowAccelChar := False;
  Body.Caption := 'Helps us know where to post. Sent once, anonymously.';
  Body.AdjustHeight;
  Top := Body.Top + Body.Height + ScaleY(12);
  AddHeardRadio('youtube', 'YouTube', Top);
  AddHeardRadio('reddit', 'Reddit', Top);
  AddHeardRadio('google', 'Google', Top);
  AddHeardRadio('friend', 'A friend', Top);
  AddHeardRadio('other', 'Other:', Top);
  HeardOther := TNewEdit.Create(HeardPage);
  HeardOther.Parent := HeardPage.Surface;
  HeardOther.Left := ScaleX(70);
  HeardOther.Top := HeardRadios[4].Top - ScaleY(3);
  HeardOther.Width := ScaleX(200);
  HeardOther.MaxLength := 40;
  HeardOther.OnChange := @HeardOtherTyped;
  HeardRadios[4].Width := HeardOther.Left - ScaleX(4);
  AddHeardRadio('', 'Rather not say', Top);
  HeardRadios[5].Checked := True;
end;

// A first install: no settings from an earlier one. An update already sent its
// first-start, so it isn't asked.
function KeepNetlogParam: Boolean;
begin
  Result := ExpandConstant('{param:KEEPNETLOG|0}') = '1';
end;

function IsNewInstall: Boolean;
begin
  Result := not FileExists(ExpandConstant('{userappdata}\OnionBoard\config.json'));
end;

function HeardShown: Boolean;
begin
#ifdef PREVIEW
  Result := True;
#else
  Result := IsNewInstall and WizardIsTaskSelected('countme') and not WizardSilent;
#endif
end;

// " --heard-from <answer>" for the "--usage-count on" entry, or nothing
function HeardArg(Param: String): String;
var
  I: Integer;
  V: String;
begin
  Result := '';
  if not HeardShown then
    exit;
  V := '';
  for I := 0 to GetArrayLength(HeardRadios) - 1 do
    if HeardRadios[I].Checked then
      V := HeardKeys[I];
  if V = 'other' then
  begin
    V := Trim(HeardOther.Text);
    StringChangeEx(V, '"', '', True);
  end;
  if V <> '' then
    Result := ' --heard-from "' + V + '"';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
#ifdef PREVIEW
  Result := (PageID <> ImportPage.ID) and (PageID <> HeardPage.ID);
#else
  Result := ((PageID = ImportPage.ID) and (GetArrayLength(ImportBoxes) = 0)) or
    ((PageID = HeardPage.ID) and not HeardShown);
#endif
end;

// Next or Install on the pages before installing (there's no Ready page): Install on
// whichever is last, which can change as Count me in is ticked.
procedure UpdateInstallCaption;
var
  Last: Boolean;
begin
  if WizardForm.CurPageID = HeardPage.ID then
    Last := True
  else if WizardForm.CurPageID = ImportPage.ID then
    Last := not HeardShown
  else if WizardForm.CurPageID = wpSelectTasks then
    Last := (GetArrayLength(ImportBoxes) = 0) and not HeardShown
  else
    exit;
  if Last then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall)
  else
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
end;

procedure TasksClicked(Sender: TObject);
begin
  UpdateInstallCaption;
end;

// Windows' own style bits, to draw the box list double-buffered (see InitializeWizard)
function GetWindowLongW(hWnd: HWND; nIndex: Integer): Longint;
  external 'GetWindowLongW@user32.dll stdcall';   // sensitive-scan: allow
function SetWindowLongW(hWnd: HWND; nIndex: Integer; dwNewLong: Longint): Longint;
  external 'SetWindowLongW@user32.dll stdcall';   // sensitive-scan: allow

procedure InitializeWizard;
var
  Body, Link, Note: TNewStaticText;
begin
  // The box list stops 11 px short of its page: down to the page's bottom, eleven rows
  // (with FFmpeg offered and Count me in) fit without a scrollbar.
  WizardForm.TasksList.Height := WizardForm.TasksList.Parent.ClientHeight -
    WizardForm.TasksList.Top;
  // the box list repainted the row under the mouse on every move (a flash): draw it off-screen first
  SetWindowLongW(WizardForm.TasksList.Handle, -20,
    GetWindowLongW(WizardForm.TasksList.Handle, -20) or $02000000);   // WS_EX_COMPOSITED
  PrivacyPage := CreateCustomPage(wpWelcome, 'Your privacy',
    'What Onion Board connects to, and when');
  Body := TNewStaticText.Create(PrivacyPage);
  Body.Parent := PrivacyPage.Surface;
  Body.AutoSize := False;
  Body.WordWrap := True;
  Body.Width := PrivacyPage.SurfaceWidth;
  Body.ShowAccelChar := False;
  Body.Caption :=
    'No account, no ads. Once a day Onion Board checks for updates and, if Count me ' +
    'in is ticked, sends anonymous usage stats. Searching sounds, radio and voices go ' +
    'online only when you use them.';
  Body.AdjustHeight;
  Link := TNewStaticText.Create(PrivacyPage);
  Link.Parent := PrivacyPage.Surface;
  Link.Caption := 'See exactly what the app does online';
  Link.Cursor := crHand;
  Link.Font.Color := clHotLight;
  Link.Font.Style := [fsUnderline];
  Link.OnClick := @OpenPrivacyLink;
  Link.Top := Body.Top + Body.Height + ScaleY(10);
  OfflineBox := TNewCheckBox.Create(PrivacyPage);
  OfflineBox.Parent := PrivacyPage.Surface;
  OfflineBox.Top := Link.Top + Link.Height + ScaleY(18);
  OfflineBox.Width := PrivacyPage.SurfaceWidth;
  OfflineBox.Height := ScaleY(17);
  OfflineBox.Caption := 'Offline mode: Onion Board never goes online at all';
  OfflineBox.Checked := (ExpandConstant('{param:OFFLINE|0}') = '1') or ConfigIsOffline;
  Note := TNewStaticText.Create(PrivacyPage);
  Note.Parent := PrivacyPage.Surface;
  Note.AutoSize := False;
  Note.WordWrap := True;
  Note.Left := ScaleX(18);
  Note.Width := PrivacyPage.SurfaceWidth - ScaleX(18);
  Note.Top := OfflineBox.Top + OfflineBox.Height + ScaleY(2);
  Note.ShowAccelChar := False;
  Note.Caption := 'No update checks, searching, radio or downloads, from its first start. ' +
    'Switch it off any time in Settings > Privacy & security.';
  Note.AdjustHeight;
  PagesBottom := WizardForm.InnerNotebook.Top + WizardForm.InnerNotebook.Height;
  Bunny := WizardForm.WizardSmallBitmapImage;
  BunnyRight := Bunny.Left + Bunny.Width;
  WizardForm.TasksList.ShowHint := True;
  CreateImportPage;
  CreateHeardPage;
  CreateDiscordLink;
  WizardForm.TasksList.OnClickCheck := @TasksClicked;
end;

// Offline mode ticked: untick the boxes that download (once, so ticking one again
// sticks) and grey out Tor, saying why. Unticked again: back to the defaults.
// The header, just tall enough for the page's heading and subheading (the subheading
// sized to its own text, not two lines), and the page starting close under it.
// Inno's own header is as tall as the bunny, which left a big gap there; the whole
// bunny is scaled down to fit (an image can't hang over the page below it).
procedure LayoutHeader;
var
  Name, Desc: TNewStaticText;
  PanelH: Integer;
begin
  Name := WizardForm.PageNameLabel;
  Desc := WizardForm.PageDescriptionLabel;
  Name.Top := ScaleY(12);
  Desc.Top := Name.Top + Name.Height + ScaleY(2);
  Desc.AdjustHeight;
  PanelH := Desc.Top + Desc.Height + ScaleY(8);
  WizardForm.MainPanel.Height := PanelH;
  WizardForm.Bevel1.Top := PanelH;
  WizardForm.InnerNotebook.Top := PanelH;
  WizardForm.InnerNotebook.Height := PagesBottom - WizardForm.InnerNotebook.Top;
  Bunny.Stretch := True;
  Bunny.Top := ScaleY(4);
  Bunny.Height := PanelH - ScaleY(8);
  Bunny.Width := Bunny.Height;
  Bunny.Left := BunnyRight - Bunny.Width;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  I: Integer;
  Lbl: TNewStaticText;
  Bottom: Integer;
begin
  if (CurPageID <> wpWelcome) and (CurPageID <> wpFinished) then
    LayoutHeader;
  if CurPageID = wpFinished then
    PlaceDiscordLink;
  UpdateInstallCaption;
  if (CurPageID <> wpSelectTasks) or WizardSilent then
    exit;
  // The cable isn't needed (sounds go straight into the mic), so its box is unticked
  // even if an old install ticked it (Inno remembers boxes); someone who wants the
  // cable ticks it. Silent installs keep what the last install chose.
  if not CableUnticked then
    WizardSelectTasks('!vbcable');
  CableUnticked := True;
  if OfflineChosen and not OfflineApplied then
    WizardSelectTasks('!vbcable,!ffmpeg,!livevoice,!tor')
  else if OfflineApplied and not OfflineChosen then
    WizardSelectTasks('ffmpeg');
  OfflineApplied := OfflineChosen;
  for I := 0 to WizardForm.TasksList.Items.Count - 1 do
    if (Pos('(Tor)', WizardForm.TasksList.ItemCaption[I]) > 0) then
    begin
      if TorCaption = '' then
        TorCaption := WizardForm.TasksList.ItemCaption[I];
      WizardForm.TasksList.ItemEnabled[I] := not OfflineChosen;
      if OfflineChosen then
        WizardForm.TasksList.ItemCaption[I] := 'Hide my internet address (Tor): off, ' +
          'because Offline mode is ticked'
      else
        WizardForm.TasksList.ItemCaption[I] := TorCaption;
    end;
  // The list can't give one box its own tooltip, so in Offline mode the whole list
  // explains the greyed-out Tor box.
  if OfflineChosen then
    WizardForm.TasksList.Hint := 'Tor is greyed out because Offline mode is ticked (one ' +
      'page back). In Offline mode Onion Board never goes online, so it would never use ' +
      'Tor. Go Back and untick Offline mode to pick it.'
  else
    WizardForm.TasksList.Hint := '';
  // A line above the boxes only in Offline mode (the heading says the rest), wrapped
  // to fit, with the list right under it.
  Lbl := WizardForm.SelectTasksLabel;
  Bottom := WizardForm.TasksList.Top + WizardForm.TasksList.Height;
  Lbl.Visible := OfflineChosen;
  if OfflineChosen then
  begin
    Lbl.Caption := 'Offline mode is on, so the boxes that download things are ' +
      'unticked. Tick one and this installer downloads it; Onion Board itself stays ' +
      'offline.';
    Lbl.WordWrap := True;
    Lbl.AdjustHeight;
    WizardForm.TasksList.Top := Lbl.Top + Lbl.Height + ScaleY(8);
  end
  else
    WizardForm.TasksList.Top := Lbl.Top;
  WizardForm.TasksList.Height := Bottom - WizardForm.TasksList.Top;
end;

// The import page's boxes: one line per ticked one in a note for the app's first
// start, which does the copying (soundboard/otherboards/__init__.py). A silent install only
// for the apps /IMPORT= names: nobody saw the boxes.
procedure QueueImports;
var
  Keys: String;
  I: Integer;
begin
  Keys := '';
  for I := 0 to GetArrayLength(ImportBoxes) - 1 do
    if ImportBoxes[I].Checked and
       (not WizardSilent or ListedIn('IMPORT', ImportKeys[I])) then
      Keys := Keys + ImportKeys[I] + #13#10;
  if Keys = '' then
    exit;
  ForceDirectories(ExpandConstant('{userappdata}\OnionBoard'));
  SaveStringToFile(ExpandConstant('{userappdata}\OnionBoard\import-from'), Keys, False);
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

// installing.txt beside the exe while the files are replaced (soundboard/core/bootmark.py
// INSTALLING): the app started meanwhile (a double-click mid-update) quits quietly
// instead of loading half-copied libraries ("Unhandled exception in script", one box per
// click). Gone before the app is opened again, and whatever way setup ends.
var
  InstallingMark: String;
  OldExe: String;

procedure StartInstallingMark;
begin
  ForceDirectories(ExpandConstant('{app}'));
  InstallingMark := ExpandConstant('{app}\installing.txt');
  SaveStringToFile(InstallingMark, 'Onion Board setup is replacing these files.', False);
end;

procedure EndInstallingMark;
begin
  if InstallingMark <> '' then
    DeleteFile(InstallingMark);
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

// The cable step, in three parts so the installer never sits frozen on it:
//  1. leaving the boxes page with the cable ticked: download and check VB-Audio's setup
//     in the background (install-vbcable.ps1 -Prefetch), while the user reads on;
//  2. Install clicked: start the script without waiting, so Windows' permission box
//     comes up at once while the files copy (and Cancel still works);
//  3. after the files: wait for its exit code (a small page, only if they haven't
//     answered Windows yet), then the restart / uninstaller bookkeeping.
var
  CablePrefetched, CableStarted, CableDone, CableHad: Boolean;

function CableScriptPath: String;
begin
  Result := ExpandConstant('{tmp}\install-vbcable.ps1');
  if not FileExists(Result) then
    ExtractTemporaryFile('install-vbcable.ps1');
end;

function CableExitFile: String;
begin
  Result := ExpandConstant('{tmp}\cable-exit.txt');
end;

// the script's exit code (0 working, 3010 restart needed, 1 failed), or -2 while it runs
function CableExitCode: Integer;
var
  S: AnsiString;
begin
  Result := -2;
  if LoadStringFromFile(CableExitFile, S) then
    Result := StrToIntDef(Trim(String(S)), -1);
end;

procedure PrefetchCable;
var
  Code: Integer;
begin
  if CablePrefetched or not MayDownload('vbcable') or CableInstalled then
    exit;
  CablePrefetched := True;
  Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + CableScriptPath +
       '" -Prefetch "' + ExpandConstant('{tmp}\cable') + '"', '', SW_HIDE, ewNoWait, Code);
end;

function PsQuote(S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '''', '''''', True);
  Result := '''' + Result + '''';
end;

procedure StartCable;
var
  Args: String;
  Code: Integer;
begin
  CableHad := CableInstalled;
  Args := '-Silent';
  if CablePrefetched then   // silent installs never saw the boxes page: no prefetch
    Args := Args + ' -From ' + PsQuote(ExpandConstant('{tmp}\cable'));
  DeleteFile(CableExitFile);
  CableStarted := Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "& ' +
    PsQuote(CableScriptPath) + ' ' + Args + '; Set-Content -LiteralPath ' +
    PsQuote(CableExitFile) + ' -Value $LASTEXITCODE"', '', SW_HIDE, ewNoWait, Code);
end;

procedure FinishCable;
var
  Code, I: Integer;
  Page: TOutputProgressWizardPage;
begin
  if not CableStarted then
    exit;
  if CableExitCode = -2 then
  begin
    Page := CreateOutputProgressPage('Adding the virtual cable',
      'If Windows is asking for permission, click Yes.');
    Page.Show;
    try
      // SetProgress keeps the window drawing while it waits; at most 15 minutes
      for I := 0 to 3600 do
      begin
        if CableExitCode <> -2 then
          break;
        Page.SetProgress(I mod 40, 40);
        Sleep(250);
      end;
    finally
      Page.Hide;
    end;
  end;
  Code := CableExitCode;
  CableDone := True;
  CableNeedsRestart := (Code = 3010);
  // remembered for the uninstaller: a cable we put there is offered for removal first
  if (not CableHad) and ((Code = 0) or (Code = 3010)) then
    RegWriteStringValue(HKCU, 'Software\OnionBoard', 'InstalledCable', '1');
  // after that restart, open the app once by itself on the setup guide's cable step
  // (the same per-user RunOnce entry the guide sets; Windows deletes it as it runs)
  if CableNeedsRestart then
    RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\RunOnce',
      'OnionBoardResumeSetup',
      '"' + ExpandConstant('{app}\{#AppExeName}.exe') + '" --resume-setup');
end;

// Cancelled after the cable went in: Inno takes Onion Board's files back out, but the
// cable stays, so say where to remove it.
procedure DeinitializeSetup;
var
  Code: Integer;
begin
  EndInstallingMark;
  if not CableStarted or CableDone or WizardSilent then
    exit;
  Code := CableExitCode;
  if (Code = 0) or (Code = 3010) then
    MsgBox('Onion Board wasn''t installed, but the virtual cable (VB-Cable) was already ' +
      'added to your PC.' + #13#10#13#10 + 'To remove it: Windows Settings > Apps > ' +
      'Installed apps > "VBCABLE, The Virtual Audio Cable" > Uninstall.', mbInformation, MB_OK)
  else if Code = -2 then
    MsgBox('Onion Board wasn''t installed. The virtual cable (VB-Cable) may still be ' +
      'added if you click Yes on Windows'' box.' + #13#10#13#10 + 'To remove it later: ' +
      'Windows Settings > Apps > Installed apps > "VBCABLE, The Virtual Audio Cable" > ' +
      'Uninstall.', mbInformation, MB_OK);
end;

#ifdef PREVIEW
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := CurPageID <> HeardPage.ID;   // a look at the pages, never an install
end;
#else
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectTasks then
    PrefetchCable;
end;
#endif

function NeedRestart(): Boolean;
begin
  Result := CableNeedsRestart;
end;

// Straight into my mic's effect still on a mic (soundboard/mic/directmic.py's notes)
function MicEffectLeft: Boolean;
var
  Root: Integer;
begin
  if IsWin64 then Root := HKLM64 else Root := HKLM;
  Result := RegKeyExists(Root, 'SOFTWARE\OnionBoard\MicPlugin\Endpoints');
end;

// Uninstall: offer to remove the cable too. The default answer is Yes only when this
// installer put it there (other apps, e.g. Voicemeeter, may use one that was already
// installed). Silent uninstalls leave it alone.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Setup, Mine: String;
  Code, Default: Integer;
begin
  // Done: one optional question, never in a silent uninstall. Only the browser opens
  // the page (soundboard/core/feedback.py's form); nothing is sent unless they submit it.
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    // "--direct-mic remove" above couldn't take it off the mic (Windows' prompt was
    // turned down): say so, rather than leave it there without a word
    if MicEffectLeft then
      MsgBox('Onion Board''s mic effect is still on your microphone (Windows'' permission ' +
        'prompt was turned down).' + #13#10#13#10 + 'Your mic works normally: without ' +
        'Onion Board the effect passes your voice straight through. To remove it, install ' +
        'Onion Board again and uninstall it, saying Yes to Windows'' prompt.',
        mbInformation, MB_OK);
    if MsgBox('Onion Board has been removed.' + #13#10#13#10 +
        'Would you tell us why? It opens a short form in your browser (no account, ' +
        'one question). Choose No to skip.', mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', UninstallFeedbackURL + '?version={#AppVersion}&from=uninstall',
        '', '', SW_SHOWNORMAL, ewNoWait, Code);
    exit;
  end;
  if CurUninstallStep <> usUninstall then
    exit;
  // the anonymous usage count's "uninstall/<version>" (soundboard/core/usage.py): the app
  // sends it only if the count is switched on, and gives up after 15 s offline
  Exec(ExpandConstant('{app}\{#AppExeName}.exe'), '--uninstall-count', '', SW_HIDE,
       ewWaitUntilTerminated, Code);
  Setup := CableSetup;
  Mine := '';
  RegQueryStringValue(HKCU, 'Software\OnionBoard', 'InstalledCable', Mine);
  if (Setup <> '') and not UninstallSilent then
  begin
    if Mine = '1' then Default := MB_DEFBUTTON1 else Default := MB_DEFBUTTON2;
    if MsgBox('Also remove the virtual cable (VB-Cable)?' + #13#10#13#10 +
        'Onion Board doesn''t need it (your sounds go straight into your mic). Choose No if ' +
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

// The extras that download after the files (Tor, FFmpeg, live voice): each runs without
// the installer waiting on it, through a small PowerShell wrapper that notes its PID and
// exit code, while a progress page keeps the window working and Cancel is clickable.
// Cancel stops the one running (its whole process tree) and skips the rest: Onion Board
// itself is installed by then, so the Finished page still comes.
var
  ExtrasPage: TOutputProgressWizardPage;
  ExtrasCancelled: Boolean;
  ExtrasSkipped: String;

procedure ExtrasCancelClick(Sender: TObject);
begin
  if MsgBox('Stop downloading the extras? Onion Board is already installed, and you can ' +
            'add them later in the app.', mbConfirmation, MB_YESNO) = IDYES then
    ExtrasCancelled := True;
end;

// Runs `Exe Params` hidden; True with its exit code, False if cancelled or not started.
// `Later` says where to get it afterwards, for the "skipped" note.
function RunExtra(Name, Status, Exe, Params, Dir, Later: String; var Code: Integer): Boolean;
var
  Wrapper, PidFile, ExitFile: String;
  Pid: AnsiString;
  S: AnsiString;
  I, Dummy: Integer;
  OldClick: TNotifyEvent;
begin
  Result := False;
  Code := -1;
  if ExtrasCancelled then
  begin
    ExtrasSkipped := ExtrasSkipped + #13#10 + '- ' + Name + ': ' + Later;
    exit;
  end;
  Wrapper := ExpandConstant('{tmp}\extra-' + IntToStr(Random(1000000)) + '.ps1');
  PidFile := Wrapper + '.pid';
  ExitFile := Wrapper + '.exit';
  SaveStringToFile(Wrapper,
    '$PID | Set-Content -LiteralPath ' + PsQuote(PidFile) + #13#10 +
    '$p = Start-Process -FilePath ' + PsQuote(Exe) + ' -ArgumentList ' + PsQuote(Params) +
    ' -WorkingDirectory ' + PsQuote(Dir) + ' -WindowStyle Hidden -PassThru' + #13#10 +
    '$p.WaitForExit()' + #13#10 +
    'Set-Content -LiteralPath ' + PsQuote(ExitFile) + ' -Value $p.ExitCode' + #13#10, False);
  if not Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + Wrapper + '"',
              '', SW_HIDE, ewNoWait, Dummy) then
    exit;
  if ExtrasPage = nil then
    ExtrasPage := CreateOutputProgressPage('Adding the extras',
      'Onion Board is installed. Click Cancel to skip the rest.');
  ExtrasPage.SetText(Status, '');
  ExtrasPage.Show;
  OldClick := WizardForm.CancelButton.OnClick;
  WizardForm.CancelButton.OnClick := @ExtrasCancelClick;
  try
    I := 0;
    while not FileExists(ExitFile) and not ExtrasCancelled do
    begin
      WizardForm.CancelButton.Enabled := True;
      ExtrasPage.SetProgress(I mod 50, 50);   // keeps the window drawing and clickable
      Sleep(200);
      I := I + 1;
    end;
  finally
    WizardForm.CancelButton.OnClick := OldClick;
    WizardForm.CancelButton.Enabled := False;
  end;
  if ExtrasCancelled and not FileExists(ExitFile) then
  begin
    if LoadStringFromFile(PidFile, Pid) then
      Exec(ExpandConstant('{sys}	askkill.exe'), '/F /T /PID ' + Trim(String(Pid)), '',
           SW_HIDE, ewWaitUntilTerminated, Dummy);
    ExtrasSkipped := ExtrasSkipped + #13#10 + '- ' + Name + ': ' + Later;
    exit;
  end;
  if LoadStringFromFile(ExitFile, S) then
    Code := StrToIntDef(Trim(String(S)), -1);
  Result := True;
end;

// The FFmpeg box: winget's own package (Gyan.FFmpeg.Essentials).
procedure GetFfmpeg;
var
  Code: Integer;
begin
  RunExtra('M4A and video support (FFmpeg)',
    'Adding M4A and video support (FFmpeg)... this can take a minute.',
    WingetPath(''), 'install --id Gyan.FFmpeg.Essentials --exact --silent ' +
    '--disable-interactivity --accept-package-agreements --accept-source-agreements',
    ExpandConstant('{tmp}'), 'Onion Board offers it when a file needs it', Code);
end;

// The live voice box: the app sets the add-on up itself (OnionBoard.exe --install-addon,
// the same as the Voice tab's Install button), getting a Python of its own into the
// add-on's folder first when the PC has no good one (soundboard/online/pyget.py).
procedure GetLiveVoice;
var
  Code: Integer;
begin
  RunExtra('Live voice-to-speech',
    'Setting up live voice-to-speech (downloads about 300 MB, can take a few minutes)...',
    ExpandConstant('{app}\{#AppExeName}.exe'), '--install-addon live-voice',
    ExpandConstant('{app}'), 'Voice tab > Install', Code);
end;

// The "tor" box: the app downloads Tor itself (OnionBoard.exe --get-tor, the same
// routine as Settings' Get Tor button: checked against its pinned SHA-256, through the
// saved proxy if there is one). Nothing to do when this Tor is already there.
procedure GetTor;
var
  Code: Integer;
begin
  if not RunExtra('Private connection (Tor)',
           'Downloading Tor from the Tor Project (about 22 MB)... this can take a minute.',
           ExpandConstant('{app}\{#AppExeName}.exe'), '--get-tor', ExpandConstant('{app}'),
           'Settings > Connection > Get Tor', Code) then
    exit;
  if Code <> 0 then
    SuppressibleMsgBox('Tor couldn''t be downloaded, so the private connection isn''t ' +
      'ready yet. Onion Board works fine without it.' + #13#10#13#10 +
      'Where Tor is blocked, downloading it often is too. You can try again any time: ' +
      'Settings > Connection > Get Tor.',
      mbInformation, MB_OK, IDOK);
end;

// The Onion Board processes running from {app} (the app, its workers, an add-on's
// Python): how many, and with Kill, closed first. Only what CloseApplications couldn't
// close gets here: an Onion Board in another Windows session (a second account signed
// in, a remote session), or one that's stuck. Its black box is told it was closed on
// purpose, like Windows closing it, so its next start doesn't count it as a crash.
function BoardProcesses(Kill: Boolean): Integer;
var
  Script, CountFile, Lines: String;
  S: AnsiString;
  Code: Integer;
begin
  Result := 0;
  Script := ExpandConstant('{tmp}\board-procs.ps1');
  CountFile := Script + '.count';
  DeleteFile(CountFile);
  Lines :=
    '$app = ' + PsQuote(ExpandConstant('{app}') + '\') + #13#10 +
    '$p = @(Get-Process | Where-Object { $_.Path -and ' +
    '$_.Path.StartsWith($app, [StringComparison]::OrdinalIgnoreCase) })' + #13#10;
  if Kill then
    Lines := Lines +
      'if ($p.Count) {' + #13#10 +
      '  $f = Join-Path $env:APPDATA ''OnionBoard\last-run.json''' + #13#10 +
      '  try { $j = [IO.File]::ReadAllText($f) | ConvertFrom-Json;' +
      ' $j | Add-Member -Force closed_by_windows $true;' +
      ' [IO.File]::WriteAllText($f, ($j | ConvertTo-Json -Depth 8 -Compress)) } catch {}' + #13#10 +
      '  $p | Stop-Process -Force -ErrorAction SilentlyContinue' + #13#10 +
      '  $p | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue' + #13#10 +
      '}' + #13#10;
  Lines := Lines + 'Set-Content -LiteralPath ' + PsQuote(CountFile) + ' -Value $p.Count' + #13#10;
  SaveStringToFile(Script, Lines, False);
  if Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '"',
          '', SW_HIDE, ewWaitUntilTerminated, Code) and LoadStringFromFile(CountFile, S) then
    Result := StrToIntDef(Trim(String(S)), 0);
end;

// Just before OnionBoard.exe is replaced (last, see [Files]): close any copy running from
// {app}, then move the old exe aside. CloseApplications only looked before the files were
// touched; a copy started since (a double-click during the update), stuck on the
// launcher's error box or started again in between, kept the exe open, and replacing it
// failed: the silent update chose Abort and rolled back, deleting _internal. Renaming
// works even while it runs, so nothing can stop the new exe going in. The old one is
// deleted at the end if it can be, else by the next install or the uninstaller.
procedure MoveOldExeAside;
var
  Exe, Old: String;
  N: Integer;
begin
  N := BoardProcesses(True);
  if N > 0 then
    Log('Closed ' + IntToStr(N) + ' Onion Board process(es) started during the install');
  Exe := ExpandConstant('{app}\{#AppExeName}.exe');
  if not FileExists(Exe) then
    exit;
  Old := Exe + '.old';
  if FileExists(Old) and not DeleteFile(Old) then
    Old := Exe + '.old' + GetDateTimeString('yyyymmddhhnnss', #0, #0);
  if RenameFile(Exe, Old) then
  begin
    OldExe := Old;
    Log('Moved the old exe aside: ' + Old);
  end else
    Log('Could not move the old exe aside; replacing it in place');
end;

// The exe MoveOldExeAside moved: gone once nothing runs it (else the next install's
// [InstallDelete] or the uninstaller takes it).
procedure DeleteOldExe;
begin
  if (OldExe <> '') and DeleteFile(OldExe) then
    OldExe := '';
end;

// {app}\_internal can be renamed (nothing inside is open), tried for about Tries / 2 s.
// It's renamed straight back.
function InternalFree(Tries: Integer): Boolean;
var
  Dir, Probe: String;
  Attempt: Integer;
begin
  Dir := ExpandConstant('{app}\_internal');
  Probe := ExpandConstant('{app}\_internal.chk');
  Result := False;
  for Attempt := 1 to Tries do
  begin
    if RenameFile(Dir, Probe) then
    begin
      Result := True;
      break;
    end;
    Sleep(500);
  end;
  if Result and not RenameFile(Probe, Dir) then
  begin
    // never leave the folder under the wrong name
    Sleep(1000);
    if not RenameFile(Probe, Dir) then
      Log('Could not rename ' + Probe + ' back to ' + Dir);
  end;
end;

// An update clears {app}\_internal first ([InstallDelete]). If a program (antivirus, a
// leftover Onion Board or python process) holds a file in there open, that delete stops
// halfway and leaves a broken install ("Failed to load Python DLL"). So before anything
// is deleted, check the folder can be renamed: Windows refuses that while a file inside
// is open. Not in PrepareToInstall: that runs before CloseApplications has closed a
// running Onion Board, which would wrongly fail a normal update.
// An Onion Board still open after that is closed here (asked first, unless silent):
// reinstalling is what people try when it's broken, and a silent install over a running
// one used to just stop (exit code 3) with nothing changed.
procedure CheckInternalNotInUse;
var
  Moved: Boolean;
begin
  if not DirExists(ExpandConstant('{app}\_internal')) then
    exit;
  // a scanner often lets go within a second or two, so try for ~10 s
  Moved := InternalFree(20);
  if not Moved and (BoardProcesses(False) > 0) then
  begin
    Log('Onion Board is still running from ' + ExpandConstant('{app}'));
    if SuppressibleMsgBox('Onion Board is still open, so it can''t be updated. Close it ' +
         'now and carry on?' + #13#10#13#10 + 'Your sounds and settings are kept.',
         mbConfirmation, MB_YESNO, IDYES) = IDYES then
    begin
      Log('Closing it: ' + IntToStr(BoardProcesses(True)) + ' process(es)');
      Moved := InternalFree(20);
    end;
  end;
  if not Moved then
  begin
    Log('A file in ' + ExpandConstant('{app}\_internal') + ' is in use; stopping before ' +
        'anything is deleted');
    RaiseException('Onion Board can''t be updated right now: a file in its folder is in ' +
      'use by another program (antivirus, or Onion Board still running). Nothing was ' +
      'changed and your current Onion Board still works. Close it (and pause your ' +
      'antivirus for a moment), then run this installer again.');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    StartInstallingMark;
  if CurStep = ssInstall then
    CheckInternalNotInUse;
  if CurStep = ssPostInstall then
    EndInstallingMark;
  if CurStep = ssPostInstall then
    DeleteOldExe;
  // first, right after Install is clicked: Windows' permission box comes up while the
  // user is still looking, not minutes later at the end
  if (CurStep = ssInstall) and MayDownload('vbcable') then
    StartCable;
  if CurStep = ssPostInstall then
    QueueImports;
  if CurStep = ssPostInstall then
    FinishCable;
  if (CurStep = ssPostInstall) and MayDownload('ffmpeg') then
    GetFfmpeg;
  if (CurStep = ssPostInstall) and MayDownload('livevoice') then
    GetLiveVoice;
  if (CurStep = ssPostInstall) and MayDownload('tor') then
    GetTor;
  if (CurStep = ssPostInstall) and (ExtrasPage <> nil) then
    ExtrasPage.Hide;
  if (CurStep = ssPostInstall) and (ExtrasSkipped <> '') then
    SuppressibleMsgBox('Stopped. Onion Board is installed; these weren''t added:' +
      ExtrasSkipped, mbInformation, MB_OK, IDOK);
end;
