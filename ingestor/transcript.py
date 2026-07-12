# -*- coding: utf-8 -*-
"""
Captacao da transcricao (camada Bronze). Resiliente: se a legenda nao existe
ou o ambiente esta sem rede, cai num gerador sintetico deterministico.

IpBlocked (rajada de requisicao -> YouTube bloqueia o IP) NAO e a mesma coisa
que "video sem legenda" -- e temporario e se resolve sozinho depois de um
tempo. Por isso e' propagado (nao vira lista vazia): quem chama (pipeline.py)
decide abortar o ciclo em vez de continuar acumulando falha atras de falha
com a mesma causa.
"""
from __future__ import annotations
import random
import time


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


def _para_trechos(fetched) -> list[dict]:
    return [{"text": s.text, "start": s.start, "duration": s.duration}
           for s in fetched]


def _qualquer_transcricao_disponivel(api, video_id: str, idiomas: list[str]) -> list[dict]:
    """Fallback quando nenhum dos idiomas preferidos tem legenda: pega
    qualquer transcricao disponivel (prioriza manual sobre auto-gerada) e
    traduz pra pt se der -- melhor ter o video na analise num idioma
    "torto" (a deteccao de jogo/elenco funciona igual, so contexto_jogo/
    resultado em PT que fica sem sinal) do que descartar o video inteiro."""
    try:
        lista = list(api.list(video_id))
    except Exception:
        return []
    if not lista:
        return []
    lista.sort(key=lambda t: t.is_generated)   # manual antes de auto-gerada
    alvo = lista[0]
    if alvo.language_code not in idiomas and getattr(alvo, "is_translatable", False):
        try:
            alvo = alvo.translate("pt")
        except Exception:
            pass
    try:
        return _para_trechos(alvo.fetch())
    except Exception:
        return []


def extrair_transcricao(video_id: str, idiomas: list[str],
                        vocabulario: list[str], modo_demo: bool,
                        retry_backoff_seg: int = 20) -> list[dict]:
    if modo_demo or video_id.startswith("demo_"):
        return _sintetico(video_id, vocabulario)

    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import RequestBlocked, CouldNotRetrieveTranscript

    api = YouTubeTranscriptApi()                  # API v1.x
    for tentativa in (1, 2):
        try:
            fetched = api.fetch(video_id, languages=idiomas)
            return _para_trechos(fetched)
        except RequestBlocked:
            if tentativa == 1 and retry_backoff_seg:
                time.sleep(retry_backoff_seg)
                continue
            raise   # ainda bloqueado apos o retry -- deixa o pipeline abortar o ciclo
        except CouldNotRetrieveTranscript:
            # sem legenda nos idiomas preferidos -- tenta qualquer transcricao
            # disponivel antes de desistir de vez (aumenta a volumetria real).
            return _qualquer_transcricao_disponivel(api, video_id, idiomas)
    return []
