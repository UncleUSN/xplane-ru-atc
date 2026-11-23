# Лицензии сторонних компонентов

Это сводка по официальным текстам на 23 ноября 2026 года, со ссылками.
Это не юридическое заключение и не выбор лицензии RU ATC: файла `LICENSE` у проекта нет, его добавит владелец.

Программа не распространяет X-Plane, Zibo 737 и веса моделей. Модели Vosk и Silero пользователь получает с сайтов авторов (установщик или первый запуск).

## Можно ли продавать программу как есть

**Нет.** Продавать текущую сборку, в которой диспетчер говорит голосом Silero `v4_ru`, нельзя.

Блокер — модель и код Silero, которыми программа пользуется сейчас (`voice/tts.py` грузит `v4_ru` через `torch.hub` из `snakers4/silero-models`).

* Файл [LICENSE](https://github.com/snakers4/silero-models/blob/master/LICENSE) репозитория — полный текст **CC BY-NC-SA 4.0**.
* Значок в README пишет «CC BY-NC 4.0» (без SA), раздел Licence — «CC-NC-BY». Расхождение есть. Опираться нужно на файл `LICENSE`: в нём есть и некоммерческое ограничение, и ShareAlike.
* Некоммерческое использование: материал нельзя применять в продукте, основная цель которого — коммерческая выгода или денежная компенсация. Продажа RU ATC с этим голосом такой целью и является. То, что вес скачивает пользователь, а не установщик, ограничение не снимает: лицензия про использование, не только про вкладывание файла в git.
* ShareAlike относится к переработкам модели. Программа модель не дообучает, но закрытая лицензия продукта с этой моделью внутри всё равно не стыкуется с NC.
* Коммерческую лицензию Silero продаёт отдельно. Публичной цены на `v4_ru` нет: [оферта](https://silero.ai/offer/) считает стоимость индивидуально, адрес — [hello@silero.ai](mailto:hello@silero.ai), то же на [странице «О нас»](https://silero.ai/about/). Страница [Licensing and Tiers](https://github.com/snakers4/silero-models/wiki/Licensing-and-Tiers) описывает STT Community Edition (некоммерческий) и Enterprise, а не прайс на голоса `v4_ru`.

Остальное продаже само по себе не запрещает, но требует соблюдения условий (уведомления, для LGPL — возможность заменить библиотеку) и двух отдельных вопросов: имя X-Plane и разрешение Zibo. Они ниже, в своих разделах.

### Чем заменить Silero, если продавать

1. **Купить лицензию Silero** на тот же `v4_ru` (письмо на hello@silero.ai). Код можно не менять, если коммерческий пакет совпадает с текущим API. Это самый прямой путь сохранить голоса aidar, baya, kseniya, xenia, eugene.
2. **Модели Silero `v5_cis_base` и `v5_cis_base_nostress`** выпущены под [MIT](https://github.com/snakers4/silero-models/blob/master/LICENSE_CIS). В README Silero прямо сказано, что все модели идут под основной лицензией, кроме этих base-моделей. У них есть русские дикторы с префиксом `ru_`, это не aidar/baya/kseniya/xenia/eugene. Для русского (славянского) текста ударения всё равно нужно ставить вручную (`к+ошка`), в том числе у варианта nostress. Сейчас программа эти модели не загружает: в `tts.py` зашит `v4_ru`.
3. **Piper, голоса `ru_RU-denis-medium` и `ru_RU-dmitri-medium`.** Список [COMMERCIAL_USE.md](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/COMMERCIAL_USE.md) относит их цепочку обучения к CC0, только качество medium и только ту переобученную копию, у которой карточка модели не говорит про базу lessac. Движок `piper1-gpl` — GPL-3.0; вшивать его в закрытую программу нельзя. Старый движок rhasspy/piper был MIT. Практичный путь — гонять ONNX-голос через onnxruntime (MIT), отдельным процессом или библиотекой, и класть рядом `MODEL_CARD` конкретного скачанного файла. Перед релизом карточку нужно прочитать: проект Piper сам пишет, что это не юридическая гарантия.
4. **Голос Windows через pyttsx3** уже есть запасным вариантом. Библиотека — MPL-2.0, голос Microsoft (например, Irina) в программу не входит, он установлен в Windows пользователя. Качество ниже, голос один. Для продажи без нейросетевого синтеза этого достаточно, если убрать зависимость от Silero.
5. **edge-tts для продажи не подходит.** Библиотека — LGPL-3.0, а ходит она в онлайн-сервис Microsoft в обход обычного речевого API. В установщик она не входит.

Vosk продаже не мешает: и библиотека, и обе модели установщика — Apache-2.0. Нужно сохранить текст лицензии и уведомления. Они есть в этом файле, установщик копирует его в папку программы.

## Модели Vosk в установщике

Обе строки взяты с официальной таблицы <https://alphacephei.com/vosk/models> (раздел Russian). В колонке License у обеих указано **Apache 2.0**.

| Модель | Архив | В таблице Vosk |
| --- | --- | --- |
| vosk-model-small-ru-0.22 | <https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip> | 45M, лёгкая, Apache 2.0 |
| vosk-model-ru-0.42 | <https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip> | 1.8G, большая, Apache 2.0 |

Там же, в блоке «Russian Other», лежат `vosk-model-ru-0.22` и `vosk-model-ru-0.10`. У них тоже Apache 2.0, но установщик их не предлагает и программа сама их не качает.

Текст Apache-2.0: <https://www.apache.org/licenses/LICENSE-2.0>.

## Библиотека Vosk

Репозиторий [alphacep/vosk-api](https://github.com/alphacep/vosk-api), файл [COPYING](https://github.com/alphacep/vosk-api/blob/master/COPYING) — **Apache 2.0**. Классификатор PyPI пакета `vosk` тот же: Apache Software License. Страница пакета: <https://pypi.org/project/vosk/>.

## Silero: модели и код

| Что | Лицензия | Где написано |
| --- | --- | --- |
| Репозиторий целиком, включая `v4_ru` (aidar, baya, kseniya, xenia, eugene) | CC BY-NC-SA 4.0 | [LICENSE](https://github.com/snakers4/silero-models/blob/master/LICENSE) |
| Как проект сам это называет | значок «CC BY-NC 4.0»; внизу README — «CC-NC-BY», исключение для base CIS | [README](https://github.com/snakers4/silero-models/blob/master/README.md) |
| `v5_cis_base`, `v5_cis_base_nostress` | MIT | [LICENSE_CIS](https://github.com/snakers4/silero-models/blob/master/LICENSE_CIS) |
| Файл веса `v4_ru`, который качает torch.hub | тот же репозиторий | <https://models.silero.ai/models/tts/ru/v4_ru.pt> (адрес из [models.yml](https://github.com/snakers4/silero-models/blob/master/models.yml)) |
| Коммерческая лицензия | индивидуально, не опубликована для `v4_ru` | <https://silero.ai/offer/>, hello@silero.ai |

Код загрузчика, который исполняет программа, — этот же репозиторий (`torch.hub.load("snakers4/silero-models")`). Отдельной MIT-лицензии на `hubconf.py` нет.

Текст CC BY-NC-SA 4.0: <https://creativecommons.org/licenses/by-nc-sa/4.0/>.

## Сборка: PyInstaller и Inno Setup

**PyInstaller** — GPL-2.0-or-later с исключением на загрузчик (Bootloader Exception).

* Текст: [COPYING.txt](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt).
* Кратко для тех, кто собирает программу: [License](https://pyinstaller.org/en/latest/license.html).
* Исключение разрешает вшить скомпилированный загрузчик в чужую программу и распространять результат без условий GPL из-за самого загрузчика. Готовый `RU-ATC.exe` можно поставлять под лицензией владельца. Менять исходники PyInstaller и распространять уже изменённый PyInstaller — по GPL. Рядом с exe лицензию PyInstaller класть не требуется: так написано в их кратком разъяснении.
* Часть файлов PyInstaller (run-time hooks, fake-modules) — Apache-2.0, подмодуль `isolated` — ещё и MIT. Это лицензии самих файлов PyInstaller, не программы.

**Inno Setup.** Файл [license.txt](https://jrsoftware.org/files/is/license.txt): пользоваться можно для любых целей, включая коммерческие программы; при распространении самого Inno Setup нужно сохранять уведомления об авторстве. Отдельно Jordan Russell [просит](https://jrsoftware.org/inno-setup/purchase) коммерческих пользователей с выручкой выше 5 000 долларов США купить лицензию. Там же прямо сказано, что покупка не является жёстким требованием. Установщики без ключа не помечаются как «нелицензионные».

## Зависимости Python, которые работают в программе

Версии в `requirements.txt` — нижние границы. Лицензия сверена по репозиторию и карточке PyPI.

| Пакет | Лицензия | Источник |
| --- | --- | --- |
| PyYAML | MIT | <https://github.com/yaml/pyyaml/blob/master/LICENSE> |
| websocket-client | Apache-2.0 | <https://github.com/websocket-client/websocket-client/blob/master/LICENSE> |
| numpy | BSD-3-Clause и ещё 0BSD, MIT, Zlib, CC0-1.0 у отдельных частей | <https://github.com/numpy/numpy/blob/main/LICENSE.txt>, карточка <https://pypi.org/project/numpy/> |
| sounddevice | MIT | <https://github.com/spatialaudio/python-sounddevice/blob/master/LICENSE> |
| PortAudio (его использует sounddevice) | MIT | <http://www.portaudio.com/license.html> |
| scipy | BSD-3-Clause; в колесе ещё OpenBLAS и LAPACK на BSD-подобных условиях | <https://github.com/scipy/scipy/blob/main/LICENSE.txt> |
| keyboard | MIT | <https://github.com/boppreh/keyboard/blob/master/LICENSE.txt> |
| pygame | LGPL-2.1 | <https://github.com/pygame/pygame/blob/main/docs/LGPL.txt>, README: закрытые и коммерческие игры допустимы, правки самого pygame нужно открывать |
| vosk | Apache-2.0 | см. выше |
| pyttsx3 | MPL-2.0 | <https://github.com/nateshmbhat/pyttsx3> (поле license в PyPI — `MPL-2.0`) |
| torch | BSD-3-Clause у основного текста [LICENSE](https://github.com/pytorch/pytorch/blob/main/LICENSE). Карточка PyPI добавляет для вложенного кода Apache-2.0, Apache-2.0 WITH LLVM-exception, BSD-2-Clause, BSL-1.0, ISC, MIT, Zlib | <https://pypi.org/project/torch/> |
| omegaconf | BSD-3-Clause | <https://github.com/omry/omegaconf/blob/master/LICENSE> |

pygame нужен только для кнопки джойстика, pyttsx3 — запасной синтез. LGPL-2.1 и MPL-2.0 не запрещают коммерческую программу. При поставке exe нужно сохранить текст LGPL/MPL и не лишать пользователя возможности заменить библиотеку. Сборка onedir кладёт бинарные модули в `_internal`, их можно подменить. Перед продажей это стоит ещё раз сверить с юристом: вопрос «or later» у pygame в их трекере не закрыт одним предложением.

В `requirements.txt` закомментированы и в установщик не входят:

| Пакет | Лицензия | Замечание |
| --- | --- | --- |
| faster-whisper | MIT | <https://github.com/SYSTRAN/faster-whisper> |
| edge-tts | LGPL-3.0 | <https://github.com/rany2/edge-tts>. Плюс условия сервиса Microsoft, см. выше |
| miniaudio | MIT | <https://github.com/irmen/pyminiaudio> |

## X-Plane Web API и Zibo

**Web API.** Описание интерфейса: [X-Plane local Web API](https://developer.x-plane.com/article/x-plane-web-api/) (обновление 20 октября 2026). Отдельной платы или запрета коммерческих внешних программ в этой статье нет. Программа ходит на `localhost:8086` к уже запущенному симулятору и не содержит файлов X-Plane. Копия X-Plane 12 должна быть у пользователя.

Заголовки Plugin SDK, которые лежат рядом с [XLua](https://github.com/X-Plane/XLua/blob/master/SDK/license.txt), разрешают использовать SDK, в том числе продавать собранное на нём, и запрещают использовать имена авторов, X-Plane и Laminar Research так, будто они рекомендуют продукт. RU ATC этот SDK не вшивает (связи идут по HTTP, не через XPLM). Название «для X-Plane» в описании — указание совместимости, не знак официального продукта Laminar. Так и нужно писать в магазине: не «официальный диспетчер X-Plane».

**Zibo 737.** Файлы самолёта в репозиторий и установщик не входят. Программа читает datarefs `laminar/B738/...` у той копии, которую пользователь поставил сам. Текст «READ FIRST – LICENSE and TERMS OF USE» из поставки Zibo в этот репозиторий не скачивался. Публично его цитируют на форуме X-Plane.org: файлы можно качать и использовать, но нельзя использовать их для коммерческих или некоммерческих продуктов без явного разрешения авторов ([тема](https://forums.x-plane.org/forums/topic/337565-trying-to-reach-authors-any-other-contact-options/)). Модератор в той же теме пишет, что молчание не равно согласию. Чтение datarefs — не переупаковка `B738.a_fms.lua`, но оговорка про «продукты» широкая. Перед продажей версии, которая имеет смысл только с Zibo, владельцу нужно письменно спросить авторов Zibo.
