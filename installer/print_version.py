"""Напечатать __version__, не импортируя пакет (сборщику ещё не нужен yaml)."""
import ast
from pathlib import Path

text = (Path(__file__).resolve().parent.parent / "ru_atc" / "__init__.py").read_text(encoding="utf-8")
for line in text.splitlines():
    if line.startswith("__version__"):
        print(ast.literal_eval(line.split("=", 1)[1].strip()))
        break
else:
    raise SystemExit("в ru_atc/__init__.py нет __version__")
