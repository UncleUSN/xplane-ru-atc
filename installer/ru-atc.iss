; Установщик RU ATC.
; Собирать скриптом installer\build.ps1: он подставляет /DMyAppVersion из ru_atc\__init__.py
; и перед компиляцией генерирует installer\generated\ (радиокнопки и config.yaml).
; Нужен Inno Setup 6.3 или новее (x64compatible). Архив Vosk качается в {app}\models,
; не в {tmp}: временный каталог Windows часто лежит на системном диске.
;
; Относительные пути ниже считаются от ЭТОГО файла (каталог installer\), не от корня
; репозитория и не от текущей папки. Один «..» — это корень:
;   OutputDir  -> <корень>\dist\installer\RU-ATC-<версия>-setup.exe
;   Source     -> <корень>\dist\RU-ATC\*
; Лишний «..» увёл бы вывод на каталог выше репозитория.

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
; Ресурс версии Windows принимает только числа. Строка 0.3.3-beta остаётся в AppVersion.
#ifndef MyVersionInfo
  #define MyVersionInfo "0.3.3.0"
#endif
VersionInfoVersion={#MyVersionInfo}
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
Source: "download_model.ps1"; Flags: dontcopy
Source: "set_xplane_path.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Запустить RU ATC"; Flags: nowait postinstall skipifsilent

[Code]
#include "generated/catalog.pas"

var
  DownloadProgress: TOutputProgressWizardPage;
  XPlanePage: TInputDirWizardPage;
  ModelPage: TWizardPage;
  ModelList: TNewCheckListBox;
  VoskItemIndex: array of Integer;
  SpeakerItemIndex: array of Integer;
  VoskZipPath: String;
  InstallSucceeded: Boolean;

function FirstInstallPath: String;
var
  Lines: TArrayOfString;
  I: Integer;
  S, Path: String;
begin
  Result := '';
  Path := ExpandConstant('{localappdata}\x-plane_install_12.txt');
  if not LoadStringsFromFile(Path, Lines) then
    Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    S := Trim(Lines[I]);
    if (S = '') or (S = 'I') or (S = 'A') or (Length(S) < 3) then
      Continue;
    if (Length(S) <= 6) and (Pos('Version', S) > 0) then
      Continue;
    Result := S;
    Exit;
  end;
end;

function HasXPlaneData(Dir: String): Boolean;
begin
  Result := DirExists(AddBackslash(Dir) + 'Resources\default data');
end;

function DetectXPlane: String;
var
  Candidates: TArrayOfString;
  I: Integer;
  FromList: String;
begin
  Result := '';
  FromList := FirstInstallPath;
  if (FromList <> '') and HasXPlaneData(FromList) then
  begin
    Result := FromList;
    Exit;
  end;
  SetArrayLength(Candidates, 5);
  Candidates[0] := 'C:\X-Plane 12';
  Candidates[1] := 'D:\X-Plane 12';
  Candidates[2] := 'E:\X-Plane 12';
  Candidates[3] := ExpandConstant('{commonpf32}\Steam\steamapps\common\X-Plane 12');
  Candidates[4] := 'D:\SteamLibrary\steamapps\common\X-Plane 12';
  for I := 0 to GetArrayLength(Candidates) - 1 do
    if HasXPlaneData(Candidates[I]) then
    begin
      Result := Candidates[I];
      Exit;
    end;
  { Неподтверждённый путь из списка установок не подставляем: в тихом режиме
    мастер иначе упрётся в предупреждение и остановится. }
end;

function ConfirmXPlaneDir(Dir: String): Boolean;
var
  Answer: Integer;
begin
  Result := True;
  Dir := Trim(Dir);
  if Dir = '' then
  begin
    Answer := SuppressibleMsgBox(
      'Папка X-Plane 12 не указана. Частоты и планы FMS программа будет искать сама, ' +
      'а путь можно дописать в config.yaml (flight_plan_import.xplane_path). Продолжить без папки?',
      mbConfirmation, MB_YESNO, IDYES);
    Result := Answer = IDYES;
    Exit;
  end;
  if not HasXPlaneData(Dir) then
  begin
    Answer := SuppressibleMsgBox(
      'В «' + Dir + '» нет папки Resources\default data. Это не похоже на установку X-Plane 12.' + #13#10 +
      'Всё равно записать этот путь в config.yaml?',
      mbError, MB_YESNO, IDNO);
    Result := Answer = IDYES;
  end;
end;

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
  Result := 'config-' + VoskId(SelectedVosk) + '-' + SpeakerId(SelectedSpeaker) + '.yaml';
end;

function DirUnderProgramFiles(Dir: String): Boolean;
var
  U, Root: String;
  Roots: TArrayOfString;
  I: Integer;
begin
  Result := False;
  U := Uppercase(AddBackslash(Dir));
  SetArrayLength(Roots, 4);
  Roots[0] := ExpandConstant('{commonpf}');
  Roots[1] := ExpandConstant('{commonpf32}');
  Roots[2] := ExpandConstant('{commonpf64}');
  Roots[3] := ExpandConstant('{pf}');
  for I := 0 to GetArrayLength(Roots) - 1 do
  begin
    Root := Uppercase(AddBackslash(Roots[I]));
    if (Root <> '\') and (Length(Root) > 3) and (Pos(Root, U) = 1) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function DirIsWritable(Dir: String): Boolean;
var
  Probe: String;
begin
  Result := False;
  if not ForceDirectories(Dir) then
    Exit;
  Probe := AddBackslash(Dir) + 'ru-atc-write.tmp';
  if not SaveStringToFile(Probe, 'ok', False) then
    Exit;
  DeleteFile(Probe);
  Result := True;
end;

function VoskZipFile: String;
begin
  Result := ExpandConstant('{app}\models\' + VoskId(SelectedVosk) + '.zip');
end;

{ Архив пишется сразу в папку установки, не во временный каталог Windows. }
function DownloadVoskZip(Url, Dest: String): Boolean;
var
  Params: String;
  Rc: Integer;
begin
  Result := False;
  Rc := -1;
  if not DirIsWritable(ExtractFileDir(Dest)) then
    Exit;
  DeleteFile(Dest + '.part');
  ExtractTemporaryFile('download_model.ps1');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\download_model.ps1') +
    '" -Url "' + Url + '" -Dest "' + Dest + '"';
  Log('Скачиваю модель Vosk в ' + Dest);
  DownloadProgress.SetText('Скачиваю модель Vosk…', Url);
  DownloadProgress.SetProgress(0, 1);
  DownloadProgress.Show;
  try
    try
      if Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Rc) and (Rc = 0) and FileExists(Dest) then
      begin
        DownloadProgress.SetProgress(1, 1);
        Result := True;
        Exit;
      end;
      DeleteFile(Dest);
      DeleteFile(Dest + '.part');
      SuppressibleMsgBox(
        'Не удалось скачать модель Vosk в папку установки. Установка продолжится: программа попробует скачать её при первом запуске.' + #13#10 +
        'Код ' + IntToStr(Rc),
        mbError, MB_OK, IDOK);
    except
      DeleteFile(Dest);
      DeleteFile(Dest + '.part');
      SuppressibleMsgBox(
        'Не удалось скачать модель Vosk. Установка продолжится: программа попробует скачать её при первом запуске.' + #13#10 +
        GetExceptionMessage, mbError, MB_OK, IDOK);
    end;
  finally
    DownloadProgress.Hide;
  end;
end;

procedure InitializeWizard;
var
  I: Integer;
  Note: TNewStaticText;
begin
  VoskZipPath := '';
  InstallSucceeded := False;
  DownloadProgress := CreateOutputProgressPage(
    'Загрузка модели распознавания',
    'Архив пишется в папку установки (models) и удаляется после распаковки. Во временный каталог Windows он не кладётся.');

  XPlanePage := CreateInputDirPage(
    wpSelectDir,
    'Папка X-Plane 12',
    'Откуда читать навигацию и планы FMC',
    'Укажите папку, в которой лежит X-Plane.exe. Она запишется в config.yaml ' +
    '(flight_plan_import.xplane_path и navdata.xplane_path). Потом путь можно поменять в файле. ' +
    'Если папка нашлась сама, она уже подставлена.',
    False, '');
  XPlanePage.Add('Папка установки');
  XPlanePage.Values[0] := DetectXPlane;

  ModelPage := CreateCustomPage(
    XPlanePage.ID,
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
    VoskItemIndex[I] := ModelList.AddRadioButton(VoskCaption(I), '', 0, I = VoskDefault, True, nil);

  SetArrayLength(SpeakerItemIndex, SpeakerCount);
  ModelList.AddGroup('Синтез речи — Silero v4_ru, один голос', '', 0, nil);
  for I := 0 to SpeakerCount - 1 do
    SpeakerItemIndex[I] := ModelList.AddRadioButton(SpeakerCaption(I), '', 0, I = SpeakerDefault, True, nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
  ZipPath, ModelDir: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if DirUnderProgramFiles(ExpandConstant('{app}')) then
      SuppressibleMsgBox(
        'Папка «' + ExpandConstant('{app}') + '» — это «Program Files» или соседний защищённый каталог.' + #13#10 +
        'Модели, кэш навигации и журналы пишутся в папку программы. Нужна запись без повышения прав.' + #13#10 +
        'Оставьте путь по умолчанию (%LOCALAPPDATA%\RU ATC) или укажите свой каталог, например D:\RU ATC.',
        mbInformation, MB_OK, IDOK);
    Exit;
  end;
  if CurPageID = XPlanePage.ID then
  begin
    Result := ConfirmXPlaneDir(XPlanePage.Values[0]);
    Exit;
  end;
  if CurPageID <> wpReady then
    Exit;
  I := SelectedVosk;
  ModelDir := ExpandConstant('{app}\models\' + VoskId(I) + '\am');
  ZipPath := VoskZipFile;
  if DirExists(ModelDir) then
  begin
    Log('Модель уже лежит в ' + ModelDir);
    Exit;
  end;
  if not DirIsWritable(ExpandConstant('{app}\models')) then
  begin
    SuppressibleMsgBox(
      'В папку «' + ExpandConstant('{app}') + '» нет записи. Модели, кэш и журналы лежат рядом с программой.' + #13#10 +
      'Оставьте путь по умолчанию (%LOCALAPPDATA%\RU ATC) или укажите свой каталог, например D:\RU ATC. «Program Files» не подходит.',
      mbError, MB_OK, IDOK);
    Result := False;
    Exit;
  end;
  VoskZipPath := ZipPath;
  if FileExists(ZipPath) then
  begin
    Log('Архив уже лежит в папке установки: ' + ZipPath);
    Exit;
  end;
  DownloadVoskZip(VoskUrl(I), ZipPath);
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
    if not CopyFile(ExpandConstant('{tmp}\') + CfgName, ExpandConstant('{app}\config.yaml'), False) then
      MsgBox('Не удалось записать config.yaml. Скопируйте config.example.yaml и поправьте модель и голос вручную.', mbError, MB_OK);
  end
  else
    Log('config.yaml уже есть — модель и голос не перезаписаны, путь X-Plane будет обновлён');

  if Trim(XPlanePage.Values[0]) <> '' then
  begin
    ExtractTemporaryFile('set_xplane_path.ps1');
    { Хвостовой слэш перед кавычкой в командной строке Windows съедает кавычку. }
    Params := Trim(XPlanePage.Values[0]);
    while (Length(Params) > 3) and ((Params[Length(Params)] = '\') or (Params[Length(Params)] = '/')) do
      Delete(Params, Length(Params), 1);
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\set_xplane_path.ps1') +
      '" -Config "' + ExpandConstant('{app}\config.yaml') + '" -XPlane "' + Params + '"';
    if (not Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Rc)) or (Rc <> 0) then
      MsgBox('Не удалось записать папку X-Plane в config.yaml (код ' + IntToStr(Rc) +
        '). Пропишите flight_plan_import.xplane_path вручную.', mbError, MB_OK);
  end;

  if VoskZipPath <> '' then
    ZipPath := VoskZipPath
  else
    ZipPath := VoskZipFile;
  if FileExists(ZipPath) then
  begin
    Dest := ExpandConstant('{app}\models');
    ExtractTemporaryFile('extract_model.ps1');
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\extract_model.ps1') +
      '" -Zip "' + ZipPath + '" -Dest "' + Dest + '"';
    if (not Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Rc)) or (Rc <> 0) then
      MsgBox('Модель скачана, но не распаковалась (код ' + IntToStr(Rc) +
        '). При первом запуске программа попробует скачать её снова.', mbError, MB_OK);
    { Большой zip не оставляем: ни после успеха, ни после ошибки распаковки. }
    if not DeleteFile(ZipPath) then
      Log('Не удалось удалить архив ' + ZipPath);
    DeleteFile(ZipPath + '.part');
  end;
  InstallSucceeded := True;
end;

procedure DeinitializeSetup();
begin
  { Отмена до конца установки не должна оставлять архив на 1,8 ГБ. }
  if InstallSucceeded or (VoskZipPath = '') then
    Exit;
  DeleteFile(VoskZipPath);
  DeleteFile(VoskZipPath + '.part');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { config.yaml и logs\ оставляем: позывной, маршрут и журнал.
    models\ и cache\ удаляем: это скачанные веса и собранный sqlite, их можно получить снова. }
  if CurUninstallStep = usPostUninstall then
  begin
    DelTree(ExpandConstant('{app}\models'), True, True, True);
    DelTree(ExpandConstant('{app}\cache'), True, True, True);
  end;
end;
