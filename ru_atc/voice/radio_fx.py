"""Эффект «радио»: полоса 300–3400 Гц, лёгкая компрессия/перегруз, шум и щелчки."""
from __future__ import annotations

import numpy as np


def radio_effect(audio: np.ndarray, sr: int, noise: float = 0.015, seed: int | None = None) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32).flatten()
    if x.size == 0:
        return x
    rng = np.random.default_rng(seed)
    # полосовой фильтр через FFT
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    mask = (freqs >= 300) & (freqs <= 3400)
    # плавные края
    edge = np.clip((freqs - 200) / 100, 0, 1) * np.clip((3600 - freqs) / 200, 0, 1)
    spec *= np.where(mask, 1.0, edge)
    y = np.fft.irfft(spec, n=x.size)
    peak = np.max(np.abs(y)) or 1.0
    y = y / peak
    y = np.tanh(y * 2.2) / np.tanh(2.2)          # перегруз
    y += rng.normal(0, noise, y.size)             # шум эфира
    # «щелчки» тангенты в начале и в конце + короткий шум шумоподавителя
    tail = int(0.12 * sr)
    sq = rng.normal(0, noise * 6, tail).astype(np.float32)
    sq *= np.linspace(1, 0, tail)
    click = np.zeros(int(0.01 * sr), dtype=np.float32)
    click[0] = 0.6
    out = np.concatenate([click, y.astype(np.float32), click, sq])
    return (out * 0.8).astype(np.float32)
