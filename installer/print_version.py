"""Напечатать __version__, не импортируя пакет (сборщику ещё не нужен yaml).

Без аргументов — строка версии (0.3.0-beta).
С --quad — четвёрка для VersionInfoVersion Windows (0.3.0.0).
"""
import ast
import re
import sys
from pathlib import Path

text = (Path(__file__).resolve().parent.parent / "ru_atc" / "__init__.py").read_text(encoding="utf-8")
version = ""
for line in text.splitlines():
    if line.startswith("__version__"):
        version = ast.literal_eval(line.split("=", 1)[1].strip())
        break
else:
    raise SystemExit("в ru_atc/__init__.py нет __version__")

if "--quad" in sys.argv:
    nums = re.findall(r"\d+", version)[:4]
    while len(nums) < 4:
        nums.append("0")
    print(".".join(nums))
else:
    print(version)
