# -*- coding: utf-8 -*-
"""Helpers compartilhados entre discovery.py e pipeline.py."""
from __future__ import annotations
import re
import unicodedata

_DURACAO_ISO_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def duracao_iso_para_segundos(duration_iso: str) -> int:
    """Converte duracao ISO 8601 (ex.: 'PT5M12S') em segundos."""
    m = _DURACAO_ISO_RE.match(duration_iso or "")
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def slug_organizacao(nome: str) -> str:
    """'FURIA eSports' -> 'furia_esports' -- particao legivel (pasta por
    organizacao) em bronze/silver, aninhada dentro de dominio= (ver
    canais.yaml:nome). Deriva do NOME do canal, nao do channel_id, pra dar
    uma pasta que faca sentido olhando o filesystem direto."""
    nfkd = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")
