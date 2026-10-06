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
;         by default (soundboard/directmic.py, set up by the app's Quick setup), and
;         the cable is only the fallback way (downloaded from vb-audio.com,
;         signature-checked by install-vbcable.ps1; Windows asks "Yes" once)
;       * FFmpeg for m4a / aac / video files (via winget; hidden when ffmpeg is
;         already there or winget isn't)
;       * live voice-to-speech's set-up (its module itself always ships, like the
;         other add-on modules in ..\modules but ai-voices)
;       * Tor, unticked: the installer doesn't carry it. A ticked box runs
;         OnionBoard.exe --get-tor, which downloads the Tor Project's Expert Bundle
;         (soundboard/torget.py: SHA-256 pinned, the saved proxy used) into
;         %APPDATA%\OnionBoard\tor\bin (Settings > Connection's "Get Tor" button does
;         the same). A failed download says so and leaves the app working without it
;       * Keep a history of network activity, unticked: runs OnionBoard.exe
;         --keep-netlog (config netlog_keep; soundboard/netlog.py keep())
;       * a Desktop shortcut
;   - a "Bring your sounds over" page (ImportPage in [Code]), only when another
;     soundboard's board is on this PC: Soundpad's %APPDATA%\Leppsoft\soundlist.spl,
;     Resanance's %APPDATA%\Resanance\data\Resanance.db, Soundux's
;     %APPDATA%\Soundux\config.json, EXP Soundboard's last board in the registry
;     (soundboard/otherboards.py). The last page before installing: a ticked box per
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
AppPublisher=Onion Board
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
WizardSizePercent=110,100
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
WelcomeLabel2=This puts Onion Board on your PC. Your sounds go straight into your own mic, so Discord and your games hear them without changing anything there. No virtual cable or extra driver to install.%n%nNext you'll see what it connects to online, then you can tick any extras you want. When Windows asks for permission, click Yes.%n%nDid Windows or your browser warn you before this opened ("Windows protected your PC", "not commonly downloaded")? That's normal for a free app that isn't code-signed, and you got past it fine. Next time: More info, then Run anyway.
WizardSelectTasks=Pick what you want
SelectTasksDesc=Tick what you'd like. If you're not sure, leave the boxes as they are.
FinishedHeadingLabel=All done!
FinishedLabel=Onion Board is installed. It will open now and ask you a few easy questions (which mic you use, where you listen), then put your sounds straight into that mic.%n%nYou can find it later on your Desktop or in the Start menu.%n%nPrivacy: no account or ads. The only thing counted is the anonymous "still here" if you left Count me in ticked. Settings > Privacy & security shows everything the app does online, lets you switch those things off, and can send all of it through a proxy or Tor.
FinishedRestartLabel=Onion Board is installed. To finish setting up the virtual cable, Windows needs to restart your PC.%n%nAfter the restart, open Onion Board from the Start menu and it will pick up where it left off.

[Tasks]
Name: "vbcable"; Description: "The free virtual cable (VB-Cable): only if you'd rather send sounds through a cable than your mic"; GroupDescription: "Other ways to send your sounds (optional)"; Flags: unchecked
Name: "ffmpeg"; Description: "Play M4A, AAC and video files (the free FFmpeg, about 100 MB)"; GroupDescription: "Extra features (optional)"; Check: CanOfferFfmpeg
Name: "livevoice"; Description: "Set up live voice-to-speech now (needs Python, about 300 MB)"; GroupDescription: "Extra features (optional)"; Flags: unchecked
Name: "tor"; Description: "Private connection (Tor): hides your internet address (about 22 MB)"; GroupDescription: "Privacy (optional)"; Flags: unchecked
Name: "keepnetlog"; Description: "Keep a history of what Onion Board connects to (on this PC only)"; GroupDescription: "Privacy (optional)"; Flags: unchecked
Name: "countme"; Description: "Count me in: an anonymous ""still here"" once a day, so we know people use it"; GroupDescription: "Privacy (optional)"
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
#ifndef PREVIEW
Source: "..\dist\OnionBoard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

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
; "Count me in" (soundboard/usage.py): unticked, it's switched off before the first
; start, so nothing is ever sent. Ticked on a page the user saw, it's switched on (an
; old install had it off); a silent update never switches it on.
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--usage-count off"; \
  StatusMsg: "Switching off the usage count..."; \
  Tasks: not countme; Flags: runhidden waituntilterminated
; It also passes on the last page's "Where did you hear about Onion Board?".
Filename: "{app}\{#AppExeName}.exe"; Parameters: "--usage-count on{code:HeardArg}"; \
  StatusMsg: "Switching on the usage count..."; \
  Tasks: countme; Check: not WizardSilent; Flags: runhidden waituntilterminated
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
  PagesBottom: Integer;        // where the pages end (LayoutHeader keeps it)
  BunnyRight: Integer;         // the bunny's right edge in the header
  CableUnticked: Boolean;      // the cable box was unticked on the first visit
  Bunny: TBitmapImage;
  TorCaption: String;          // the Tor box's own caption (Offline mode replaces it)
  ImportPage: TWizardPage;     // "Bring your sounds over": only when one is found
  ImportBoxes: array of TNewCheckBox;
  ImportKeys: array of String; // soundboard/otherboards.py's key for each box
  ImportTop: Integer;          // where the next box goes
  HeardPage: TWizardPage;      // "Where did you hear about Onion Board?": new installs
  HeardRadios: array of TNewRadioButton;
  HeardKeys: array of String;  // what each one sends (soundboard/usage.py's HEARD)
  HeardOther: TNewEdit;        // Other's own answer

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

// EXP Soundboard remembers its last board in Java's Preferences (soundboard/expboard.py)
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
    'so your board is ready straight away. Your other app keeps its own copies, and ' +
    'nothing in it is changed.';
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
// app, sent once with the first-start count (soundboard/usage.py heard_tag, which
// drops a typed answer that doesn't look like a name). "Rather not say" is picked.
procedure CreateHeardPage;
var
  Body, Note: TNewStaticText;
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
  Body.Caption := 'It helps us know where people find it. Your pick goes once with the ' +
    'anonymous Count me in, and nothing else is sent.';
  Body.AdjustHeight;
  Top := Body.Top + Body.Height + ScaleY(12);
  AddHeardRadio('youtube', 'YouTube', Top);
  AddHeardRadio('reddit', 'Reddit', Top);
  AddHeardRadio('github', 'GitHub', Top);
  AddHeardRadio('google', 'Google', Top);
  AddHeardRadio('friend', 'A friend', Top);
  AddHeardRadio('other', 'Other:', Top);
  HeardOther := TNewEdit.Create(HeardPage);
  HeardOther.Parent := HeardPage.Surface;
  HeardOther.Left := ScaleX(70);
  HeardOther.Top := HeardRadios[5].Top - ScaleY(3);
  HeardOther.Width := ScaleX(200);
  HeardOther.MaxLength := 40;
  HeardOther.OnChange := @HeardOtherTyped;
  HeardRadios[5].Width := HeardOther.Left - ScaleX(4);
  AddHeardRadio('', 'Rather not say', Top);
  HeardRadios[6].Checked := True;
  Note := TNewStaticText.Create(HeardPage);
  Note.Parent := HeardPage.Surface;
  Note.AutoSize := False;
  Note.WordWrap := True;
  Note.Width := HeardPage.SurfaceWidth;
  Note.Top := Top + ScaleY(6);
  Note.ShowAccelChar := False;
  Note.Caption := 'For Other, just a name like Discord or TikTok. Anything else ' +
    '(an email address, a link, a number) is left out.';
  Note.AdjustHeight;
end;

// A first install: no settings from an earlier one. An update already sent its
// first-start, so it isn't asked.
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

#ifdef PREVIEW
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := CurPageID <> HeardPage.ID;   // a look at the pages, never an install
end;
#endif

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

procedure InitializeWizard;
var
  Body, Link, Note: TNewStaticText;
  Bullet: String;
begin
  Bullet := '  ' + #$2022 + '  ';
  // The box list stops 11 px short of its page: down to the page's bottom, eleven rows
  // (with FFmpeg offered and Count me in) fit without a scrollbar.
  WizardForm.TasksList.Height := WizardForm.TasksList.Parent.ClientHeight -
    WizardForm.TasksList.Top;
  PrivacyPage := CreateCustomPage(wpWelcome, 'Your privacy',
    'What Onion Board connects to, and when');
  Body := TNewStaticText.Create(PrivacyPage);
  Body.Parent := PrivacyPage.Surface;
  Body.AutoSize := False;
  Body.WordWrap := True;
  Body.Width := PrivacyPage.SurfaceWidth;
  Body.ShowAccelChar := False;
  Body.Caption :=
    'No account, no ads. On its own, Onion Board only goes online once a day: to ' +
    'check for updates, and to send an anonymous "still here" if Count me in is ' +
    'ticked. Nothing downloads until you click Update, and you can switch both off.' + #13#10#13#10 +
    'Everything else happens only when you use it:' + #13#10 +
    Bullet + 'Sounds: searching and downloading go to YouTube, SoundCloud or Myinstants.' + #13#10 +
    Bullet + 'Radio: Radio Browser (a free list of stations) and the stations you play.' + #13#10 +
    Bullet + 'Voices and add-ons: they download when you press their buttons.' + #13#10#13#10 +
    'Those sites can see your internet address. The Tor box on the next page hides it.';
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
        WizardForm.TasksList.ItemCaption[I] := 'Private connection (Tor): off, because ' +
          'Offline mode is ticked'
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
// start, which does the copying (soundboard/otherboards.py). A silent install only
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
      'Settings > Connection > Get Tor.',
      mbInformation, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    QueueImports;
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
