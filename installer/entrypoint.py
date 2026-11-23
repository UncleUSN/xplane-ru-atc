"""Точка входа PyInstaller.

``ru_atc/__main__.py`` рассчитан на ``python -m ru_atc`` и импортирует пакет
относительно себя. Загрузчик exe запускает скрипт как ``__main__``, без
пакета-родителя, поэтому относительный импорт там падает. Этот файл лежит
вне пакета и импортирует ``ru_atc`` абсолютно.

``freeze_support`` нужен до первого импорта torch: на Windows замороженный
процесс иначе зацикливается на ``multiprocessing``.
"""
import multiprocessing

multiprocessing.freeze_support()

from ru_atc.app import main

if __name__ == "__main__":
    main()
