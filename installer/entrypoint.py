"""Точка входа PyInstaller.

``ru_atc/__main__.py`` рассчитан на ``python -m ru_atc`` и импортирует пакет
относительно себя. Загрузчик exe запускает скрипт как ``__main__``, без
пакета-родителя, поэтому относительный импорт там падает. Этот файл лежит
вне пакета и импортирует ``ru_atc`` абсолютно.

``freeze_support`` нужен до первого импорта torch: на Windows замороженный
процесс иначе зацикливается на ``multiprocessing``.
"""
import os
import traceback


def _boot(msg: str) -> None:
    """Дописать строку в отчёт сборки. У оконного exe нет консоли."""
    path = os.environ.get("RU_ATC_SMOKE_REPORT")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


_boot("boot")
try:
    import multiprocessing

    multiprocessing.freeze_support()
    _boot("freeze_support")
    from ru_atc.app import main

    _boot("app imported")
except SystemExit:
    raise
except Exception:
    _boot(traceback.format_exc())
    os._exit(1)

if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            code = 0
        elif not isinstance(code, int):
            code = 1
        # os._exit, а не обычный выход: keyboard/pygame могут оставить
        # недемонический поток, и процесс тогда не завершается.
        os._exit(code)
    except Exception:
        _boot(traceback.format_exc())
        os._exit(1)
