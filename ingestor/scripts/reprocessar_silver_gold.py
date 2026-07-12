# -*- coding: utf-8 -*-
"""
Reprocessa Silver + Gold a partir do Bronze ja capturado, sem rechamar a API
(youtube_transcript_api) nem tocar no SQLite de controle (watermark/
idempotencia ficam intactos -- so os parquet de Silver/Gold sao reescritos).

Uso quando a logica de limpeza/deteccao muda e o dado ja ingerido precisa ser
reclassificado -- mesmo padrao que este projeto ja usou uma vez pra corrigir
o bug de acentuacao (ver docs/ARQUITETURA.md), agora reaproveitado pra
corrigir o bug de digito na deteccao de modalidade ("cs2"/"r6" eram removidos
antes de comparar com config/sinais.yaml).

Uso:
  python -m ingestor.scripts.reprocessar_silver_gold             # dominio "esports"
  python -m ingestor.scripts.reprocessar_silver_gold outro_dominio
"""
from __future__ import annotations
import sys
from pathlib import Path

import pandas as pd

from ..pipeline import (
    _bronze_silver, _carregar_sinais, _carregar_jogos, _carregar_elencos,
    _gold, _gold_palavras,
)
from ..state import StateStore


def _persistir_silver_no_dt(df: pd.DataFrame, dominio: str, organizacao: str,
                            dt: str, video_id: str) -> None:
    # Escreve na MESMA particao dt= do bronze de origem (nao na data de hoje)
    # -- senao o video fica duplicado (schema antigo na particao velha, novo
    # na de hoje), e organizacao=*/dt=*/*.parquet do _gold le os dois.
    base = Path(f"./datalake/silver/dominio={dominio}/organizacao={organizacao}/dt={dt}")
    base.mkdir(parents=True, exist_ok=True)
    df.to_parquet(base / f"{video_id}.parquet", index=False)


def reprocessar(dominio: str = "esports") -> dict:
    raiz = Path(f"./datalake/bronze/dominio={dominio}")
    # nao recursivo (pula comentarios/): organizacao=*/dt=*/*.parquet
    arquivos = sorted(raiz.glob("organizacao=*/dt=*/*.parquet"))
    ok, falhas = 0, 0
    for arq in arquivos:
        video_id = arq.stem
        dt = arq.parent.name.split("=", 1)[1]
        organizacao = arq.parent.parent.name.split("=", 1)[1]
        bronze = pd.read_parquet(arq)
        trechos = [
            {"text": r.text, "start": r.start, "duration": r.duration}
            for r in bronze.itertuples()
        ]
        try:
            df = _bronze_silver(video_id, trechos)
        except Exception as e:
            print(f"[falha] {video_id}: {e}")
            falhas += 1
            continue
        _persistir_silver_no_dt(df, dominio, organizacao, dt, video_id)
        ok += 1

    sinais_jogo, sinais_pos, sinais_neg = _carregar_sinais()
    jogos = _carregar_jogos()
    elencos = _carregar_elencos()
    store = StateStore()
    _gold(dominio, sinais_jogo, sinais_pos, sinais_neg, jogos, elencos, store)
    _gold_palavras(dominio)
    return {"reprocessados": ok, "falhas": falhas}


if __name__ == "__main__":
    dominio_alvo = sys.argv[1] if len(sys.argv) > 1 else "esports"
    print(reprocessar(dominio_alvo))
