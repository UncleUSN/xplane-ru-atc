const
  VoskCount = 2;
  VoskDefault = 0;
  SpeakerCount = 5;
  SpeakerDefault = 0;

function VoskId(I: Integer): String;
begin
  case I of
    0: Result := 'vosk-model-small-ru-0.22';
    1: Result := 'vosk-model-ru-0.42';
  else
    Result := '';
  end;
end;

function VoskUrl(I: Integer): String;
begin
  case I of
    0: Result := 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip';
    1: Result := 'https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip';
  else
    Result := '';
  end;
end;

function VoskCaption(I: Integer): String;
begin
  case I of
    0: Result := 'Лёгкая vosk-model-small-ru-0.22 — 45 МБ, около 300 МБ памяти, быстрее, хуже разбирает числа (по умолчанию)';
    1: Result := 'Большая vosk-model-ru-0.42 — 1,8 ГБ, точнее на речи и числах, нужно несколько ГБ памяти (большие модели Vosk — вплоть до 16 ГБ)';
  else
    Result := '';
  end;
end;

function SpeakerId(I: Integer): String;
begin
  case I of
    0: Result := 'aidar';
    1: Result := 'baya';
    2: Result := 'kseniya';
    3: Result := 'xenia';
    4: Result := 'eugene';
  else
    Result := '';
  end;
end;

function SpeakerCaption(I: Integer): String;
begin
  case I of
    0: Result := 'Silero v4_ru, голос aidar — мужской (по умолчанию)';
    1: Result := 'Silero v4_ru, голос baya — женский';
    2: Result := 'Silero v4_ru, голос kseniya — женский';
    3: Result := 'Silero v4_ru, голос xenia — женский';
    4: Result := 'Silero v4_ru, голос eugene — мужской';
  else
    Result := '';
  end;
end;
