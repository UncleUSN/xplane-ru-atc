; Установщик RU ATC.
; Собирать скриптом installer\build.ps1: он подставляет /DMyAppVersion из ru_atc\__init__.py
; и перед компиляцией генерирует installer\generated\ (радиокнопки и config.yaml).
; Нужен Inno Setup 6.3 или новее (CreateDownloadPage, x64compatible).
; Готовый setup.exe в среде подготовки этого выпуска не собирался: там нет Windows.

#ifndef MyAppVersion
  #error Запустите installer\build.ps1 — он передаёт /DMyAppVersion из ru_atc\__init__.py
#endif

#define MyAppName "RU ATC"
#define MyAppExe "RU-ATC.exe"

[Setup]
AppId={{7E2A9C14-6B0F-4E8A-9D33-1C5F8A2B4D70}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
; Ресурс версии Windows принимает только числа. Строка 0.2b — в AppVersion.
VersionInfoVersion=0.2.0.0
AppPublisher={#MyAppName}
DefaultDirName={localappdata}\RU ATC
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=RU-ATC-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayIcon={app}\{#MyAppExe}
InfoBeforeFile=welcome.txt
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Files]
#include "generated/files.iss"
Source: "..\dist\RU-ATC\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "extract_model.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Запустить RU ATC"; Flags: nowait postinstall skipifsilent

[Code]
#include "generated/catalog.pas"

var
  DownloadPage: TDownloadWizardPage;
  ModelPage: TWizardPage;
  ModelList: TNewCheckListBox;
  VoskItemIndex: array of Integer;
  SpeakerItemIndex: array of Integer;
  DownloadedVosk: String;

function SelectedVosk: Integer;
var
  I: Integer;
begin
  Result := VoskDefault;
  for I := 0 to VoskCount - 1 do
    if ModelList.Checked[VoskItemIndex[I]] then
      Result := I;
end;

function SelectedSpeaker: Integer;
var
  I: Integer;
begin
  Result := SpeakerDefault;
  for I := 0 to SpeakerCount - 1 do
    if ModelList.Checked[SpeakerItemIndex[I]] then
      Result := I;
end;

function SelectedConfigFile: String;
begin
  Result := 'config-' + VoskIds[SelectedVosk] + '-' + SpeakerIds[SelectedSpeaker] + '.yaml';
end;

procedure InitializeWizard;
var
  I: Integer;
  Note: TNewStaticText;
begin
  DownloadedVosk := '';
  DownloadPage := CreateDownloadPage(
    'Загрузка модели распознавания',
    'Архив берётся с alphacephei.com. В состав программы он не входит.',
    nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := False;

  ModelPage := CreateCustomPage(
    wpSelectDir,
    'Модели речи',
    'В каждой группе можно выбрать только один пункт.');

  Note := TNewStaticText.Create(WizardForm);
  Note.Parent := ModelPage.Surface;
  Note.Caption :=
    'Vosk скачивается сейчас с официального сайта. Silero v4_ru (около 40 МБ) ' +
    'скачивается при первом запуске с models.silero.ai. Веса в установщик не вшиты.';
  Note.Left := 0;
  Note.Top := 0;
  Note.Width := ModelPage.SurfaceWidth;
  Note.Height := ScaleY(44);
  Note.AutoSize := False;
  Note.WordWrap := True;

  ModelList := TNewCheckListBox.Create(WizardForm);
  ModelList.Parent := ModelPage.Surface;
  ModelList.Left := 0;
  ModelList.Top := Note.Height + ScaleY(6);
  ModelList.Width := ModelPage.SurfaceWidth;
  ModelList.Height := ModelPage.SurfaceHeight - ModelList.Top;
  ModelList.WantTabs := True;

  SetArrayLength(VoskItemIndex, VoskCount);
  ModelList.AddGroup('Распознавание речи — модель Vosk', '', 0, nil);
  for I := 0 to VoskCount - 1 do
    VoskItemIndex[I] := ModelList.AddRadioButton(VoskCaptions[I], '', 0, I = VoskDefault, True, nil);

  SetArrayLength(SpeakerItemIndex, SpeakerCount);
  ModelList.AddGroup('Синтез речи — Silero v4_ru, один голос', '', 0, nil);
  for I := 0 to SpeakerCount - 1 do
    SpeakerItemIndex[I] := ModelList.AddRadioButton(SpeakerCaptions[I], '', 0, I = SpeakerDefault, True, nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
  ZipPath, ModelDir: String;
begin
  Result := True;
  if CurPageID <> wpReady then
    Exit;
  I := SelectedVosk;
  ModelDir := ExpandConstant('{app}\models\' + VoskIds[I] + '\am');
  ZipPath := ExpandConstant('{tmp}\vosk-model.zip');
  if DirExists(ModelDir) then
  begin
    Log('Модель уже лежит в ' + ModelDir);
    Exit;
  end;
  if (DownloadedVosk = VoskIds[I]) and FileExists(ZipPath) then
  begin
    Log('Архив этой модели уже скачан');
    Exit;
  end;
  DeleteFile(ZipPath);
  DownloadedVosk := '';
  DownloadPage.Clear;
  DownloadPage.Add(VoskUrls[I], 'vosk-model.zip', '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      DownloadedVosk := VoskIds[I];
    except
      DeleteFile(ZipPath);
      SuppressibleMsgBox(
        'Не удалось скачать модель Vosk. Установка продолжится: программа попробует скачать её при первом запуске.' + #13#10 +
        GetExceptionMessage, mbError, MB_OK, IDOK);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  CfgName, ZipPath, Dest, Params: String;
  Rc: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;

  CfgName := SelectedConfigFile;
  if not FileExists(ExpandConstant('{app}\config.yaml')) then
  begin
    ExtractTemporaryFile(CfgName);
    if not FileCopy(ExpandConstant('{tmp}\') + CfgName, ExpandConstant('{app}\config.yaml'), False) then
      MsgBox('Не удалось записать config.yaml. Скопируйте config.example.yaml и поправьте модель и голос вручную.', mbError, MB_OK);
  end
  else
    Log('config.yaml уже есть — выбор мастера в него не записан');

  ZipPath := ExpandConstant('{tmp}\vosk-model.zip');
  if FileExists(ZipPath) then
  begin
    Dest := ExpandConstant('{app}\models');
    ExtractTemporaryFile('extract_model.ps1');
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\extract_model.ps1') +
      '" -Zip "' + ZipPath + '" -Dest "' + Dest + '"';
    if (not Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Rc)) or (Rc <> 0) then
      MsgBox('Модель скачана, но не распаковалась (код ' + IntToStr(Rc) +
        '). При первом запуске программа попробует скачать её снова.', mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { config.yaml оставляем: в нём позывной и маршрут. Модели тяжёлые — удаляем. }
  if CurUninstallStep = usPostUninstall then
    DelTree(ExpandConstant('{app}\models'), True, True, True);
end;
