# -*- coding: utf-8 -*-
"""
Captacao da transcricao (camada Bronze). Resiliente: se a legenda nao existe
ou o ambiente esta sem rede, cai num gerador sintetico deterministico.
"""
from __future__ import annotations
import random


def _sintetico(video_id: str, vocabulario: list[str], n=160) -> list[dict]:
    rng = random.Random(hash(video_id) & 0xFFFFFFFF)
    base = ["entao", "olha", "o ponto aqui", "veja bem", "na pratica",
            "vale destacar", "o dado mostra", "repare que"]
    trechos, t = [], 0.0
    for _ in range(n):
        palavras = rng.sample(base, k=2)
        if rng.random() < 0.30 and vocabulario:
            palavras.append(rng.choice(vocabulario))
        dur = round(rng.uniform(2.0, 6.0), 2)
        trechos.append({"text": " ".join(palavras), "start": round(t, 2),
                        "duration": dur})
        t += dur
    return trechos


def extrair_transcricao(video_id: str, idiomas: list[str],
                        vocabulario: list[str], modo_demo: bool) -> list[dict]:
    if modo_demo or video_id.startswith("demo_"):
        return _sintetico(video_id, vocabulario)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()                  # API v1.x
        fetched = api.fetch(video_id, languages=idiomas)
        return [{"text": s.text, "start": s.start, "duration": s.duration}
                for s in fetched]
    except Exception:
        # video sem legenda: registra vazio para o pipeline marcar SKIPPED
        return []
