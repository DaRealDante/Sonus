#define MyAppName "Sonus"
#define MyAppVersion GetEnv("KM_VERSION")
#define MyAppExe "Sonus.exe"

[Setup]
AppId={{CA6E2038-71CA-48EF-9C0D-942A89F6A086}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Ken [HD]
DefaultDirName={localappdata}\Programs\Sonus
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=Sonus_Setup_v{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; GroupDescription: "Icone:"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\Sonus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; Subkey: "Software\Classes\sonus"; ValueType: string; ValueName: ""; ValueData: "URL:Sonus"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\sonus"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\sonus\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExe},0"
Root: HKCU; Subkey: "Software\Classes\sonus\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon
Name: "{autoprograms}\Sonus - Aggiorna"; Filename: "{localappdata}\Sonus\Sorgente\INSTALLA_E_AGGIORNA.bat"; WorkingDir: "{localappdata}\Sonus\Sorgente"; IconFilename: "{app}\{#MyAppExe}"; Check: SourceExists

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Avvia Sonus"; Flags: nowait postinstall

[Code]
function SourceExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Sonus\Sorgente\sonus_build.py'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    if MsgBox('Vuoi eliminare anche playlist, canzoni scaricate, testi, video e impostazioni di Sonus?' + #13#10 + 'Se scegli No restano per una futura reinstallazione.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\Sonus'), True, True, True);
end;
