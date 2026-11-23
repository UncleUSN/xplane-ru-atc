const
  VoskCount = 2;
  VoskDefault = 0;
  SpeakerCount = 5;
  SpeakerDefault = 0;
  VoskIds: array[0..1] of String = (
    'vosk-model-small-ru-0.22',
    'vosk-model-ru-0.42'
  );
  VoskUrls: array[0..1] of String = (
    'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip',
    'https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip'
  );
  VoskCaptions: array[0..1] of String = (
    'Лёгкая vosk-model-small-ru-0.22 — 45 МБ, около 300 МБ памяти, быстрее, хуже разбирает числа (по умолчанию)',
    'Большая vosk-model-ru-0.42 — 1,8 ГБ, точнее на речи и числах, нужно несколько ГБ памяти (большие модели Vosk — вплоть до 16 ГБ)'
  );
  SpeakerIds: array[0..4] of String = (
    'aidar',
    'baya',
    'kseniya',
    'xenia',
    'eugene'
  );
  SpeakerCaptions: array[0..4] of String = (
    'Silero v4_ru, голос aidar — мужской (по умолчанию)',
    'Silero v4_ru, голос baya — женский',
    'Silero v4_ru, голос kseniya — женский',
    'Silero v4_ru, голос xenia — женский',
    'Silero v4_ru, голос eugene — мужской'
  );
