# -*- coding: utf-8 -*-
"""
Pipeline de ingestao perene — orquestra um ciclo completo para UM canal.

Fluxo de um ciclo:
  descobrir (incremental via watermark)
    -> para cada video novo e nao-ingerido (idempotencia):
         captar transcricao  (BRONZE)
         limpar + contrato    (SILVER)
       persiste parquet + atualiza estado SQLite
    -> roda analitico do dominio (GOLD)
    -> avanca o watermark do canal

Tudo escrito de forma que rodar o mesmo ciclo duas vezes NAO duplica dados.
"""
from __future__ import annotations
import re
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import polars as pl
import yaml
import pandera.pandas as pa
from pandera.pandas import Column, DataFrameSchema, Check

from .state import StateStore, content_hash
from .discovery import get_discovery
from .transcript import extrair_transcricao
from .utils import duracao_iso_para_segundos as _duracao_segundos

log = logging.getLogger("ingestor")

STOPWORDS = {"entao", "olha", "ne", "tipo", "veja", "bem", "o", "a", "que",
             "de", "e", "aqui", "isso", "na", "pratica"}

# Mesmo contrato Silver dos 10 notebooks (Desafio 1), incluindo n_palavras.
SILVER_SCHEMA = DataFrameSchema({
    "video_id":    Column(str, nullable=False),
    "ordem":       Column(int, Check.ge(0)),
    "texto_limpo": Column(str, Check.str_length(min_value=1)),
    "start":       Column(float, Check.ge(0)),
    "duration":    Column(float, Check.gt(0)),
    "n_palavras":  Column(int, Check.ge(1)),
}, coerce=True)

_SINAIS_PATH = Path(__file__).resolve().parent.parent / "config" / "sinais.yaml"


def _carregar_sinais() -> tuple[list[str], list[str]]:
    """Sinais de RESULTADO (positivo/negativo) compartilhados entre canais
    (config/sinais.yaml) — vocabulario de fala casual sobre o resultado do
    jogo, usado quando o canal nao define 'vocabulario' proprio no
    canais.yaml. Ver comentario do sinais.yaml: os canais sao vlogs de
    bastidor, nao transmissao/narracao."""
    if not _SINAIS_PATH.is_file():
        return [], []
    dados = yaml.safe_load(_SINAIS_PATH.read_text(encoding="utf-8")) or {}
    return dados.get("resultado_positivo", []), dados.get("resultado_negativo", [])


def _limpar(texto: str) -> str:
    texto = re.sub(r"[^a-zaaaeeiooouuc\s]", " ", texto.lower())
    return " ".join(t for t in texto.split()
                    if t not in STOPWORDS and len(t) > 2)


_QUARENTENA_DIR = Path("./datalake/silver/_quarentena")


def _persistir_bronze(trechos: list[dict], dominio: str, video_id: str) -> None:
    """Grava a transcricao crua (Bronze), antes de qualquer limpeza/validacao."""
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = Path(f"./datalake/bronze/dominio={dominio}/dt={dia}")
    base.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([
        {"video_id": video_id, "ordem": i, "text": t["text"],
         "start": float(t["start"]), "duration": float(t["duration"])}
        for i, t in enumerate(trechos)
    ])
    df.to_parquet(base / f"{video_id}.parquet", index=False)


def _persistir_quarentena(df: pd.DataFrame, video_id: str) -> None:
    """Grava o lote que falhou o contrato Pandera, para inspecao manual."""
    _QUARENTENA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_QUARENTENA_DIR / f"{video_id}.parquet", index=False)


def _bronze_silver(video_id, trechos) -> pd.DataFrame:
    df = pd.DataFrame([
        {"video_id": video_id, "ordem": i, "texto": t["text"],
         "start": float(t["start"]), "duration": float(t["duration"])}
        for i, t in enumerate(trechos)
    ])
    df["texto_limpo"] = df["texto"].apply(_limpar)
    df = df[df["texto_limpo"].str.len() > 0].copy()
    df["n_palavras"] = df["texto_limpo"].str.split().str.len().fillna(0).astype(int)
    bruto = df[["video_id", "ordem", "texto_limpo", "start", "duration", "n_palavras"]]
    try:
        return SILVER_SCHEMA.validate(bruto)
    except pa.errors.SchemaError:
        _persistir_quarentena(bruto, video_id)
        raise


def _persistir(df: pd.DataFrame, dominio: str, video_id: str):
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = Path(f"./datalake/silver/dominio={dominio}/dt={dia}")
    base.mkdir(parents=True, exist_ok=True)
    df.to_parquet(base / f"{video_id}.parquet", index=False)


def _gold(dominio: str, sinais_pos: list[str], sinais_neg: list[str],
          store: StateStore) -> pd.DataFrame:
    """Classifica cada VIDEO (agregando os trechos) como comentando o
    resultado (positivo/negativo) ou sem mencao a resultado ('sem_resultado'
    — o video e so vlog/bastidor aleatorio), e cruza com metricas reais de
    audiencia (view_count, like_count, comment_count, category_id) do canal.

    Os canais sao vlogs de bastidor (nao narracao/transmissao): a maior parte
    do conteudo e aleatoria, e so em um trecho especifico (as vezes nenhum)
    o jogador comenta o resultado da partida. O que interessa pro negocio
    NAO e contar mencao isolada, e sim responder: video que comenta vitoria
    tem mais audiencia que o que comenta derrota, ou que o vlog aleatorio
    sem mencao nenhuma? category_id (do YouTube) serve de proxy pra "tipo de
    video" quando o conteudo foge do padrao vlog.
    """
    src = f"./datalake/silver/dominio={dominio}/**/*.parquet"
    pos, neg = set(sinais_pos), set(sinais_neg)
    try:
        por_video = (
            pl.scan_parquet(src)
            .with_columns(pl.col("texto_limpo").str.split(" ").alias("tokens"))
            .with_columns([
                pl.col("tokens").list.eval(pl.element().is_in(list(pos))).list.sum().alias("hits_pos"),
                pl.col("tokens").list.eval(pl.element().is_in(list(neg))).list.sum().alias("hits_neg"),
            ])
            .group_by("video_id")
            .agg([
                pl.col("hits_pos").sum().alias("hits_pos"),
                pl.col("hits_neg").sum().alias("hits_neg"),
                pl.len().alias("trechos_total"),
            ])
            .with_columns(
                pl.when(pl.col("hits_pos") > pl.col("hits_neg")).then(pl.lit("resultado_positivo"))
                  .when(pl.col("hits_neg") > pl.col("hits_pos")).then(pl.lit("resultado_negativo"))
                  .otherwise(pl.lit("sem_resultado")).alias("categoria")
            )
            .collect()
            .to_pandas()
        )
    except Exception:
        return pd.DataFrame()   # ainda sem dados silver pra esse dominio

    metricas = pd.DataFrame(store.metadados_video(dominio))
    if metricas.empty:
        gold = por_video
        for col in ("view_count", "like_count", "comment_count", "category_id", "title"):
            gold[col] = None
    else:
        gold = por_video.merge(metricas, on="video_id", how="left")

    out = Path(f"./datalake/gold/dominio={dominio}")
    out.mkdir(parents=True, exist_ok=True)
    gold.to_parquet(out / "resultado_engajamento.parquet", index=False)
    return gold


def rodar_ciclo(canal: dict, glob_cfg: dict, store: StateStore) -> dict:
    """Executa um ciclo completo de ingestao para um canal. Idempotente."""
    cid, dom = canal["channel_id"], canal["dominio"]
    sinais_pos, sinais_neg = _carregar_sinais()
    # sem 'vocabulario' proprio no canal -> usa os sinais de resultado compartilhados
    vocab = canal.get("vocabulario", []) or (sinais_pos + sinais_neg)
    disc = get_discovery(glob_cfg.get("modo_demo", True))

    duracao_min = canal.get("duracao_min_seg", 0)
    watermark = store.get_watermark(cid)
    videos = disc.descobrir(cid, watermark,
                            canal.get("max_videos_por_ciclo", 5),
                            glob_cfg.get("janela_descoberta_dias", 30),
                            duracao_min)

    # backstop: a DemoDiscovery nao filtra por duracao sozinha (a real ja filtra)
    if duracao_min:
        antes = len(videos)
        videos = [v for v in videos if _duracao_segundos(v.duration_iso) >= duracao_min]
        descartados_duracao = antes - len(videos)
    else:
        descartados_duracao = 0

    modo_demo = glob_cfg.get("modo_demo", True)
    delay = glob_cfg.get("transcript_delay_seg", 2)

    novos, ingeridos, pulados, falhas, max_pub = 0, 0, 0, 0, watermark or ""
    for i, v in enumerate(videos):
        # espaca as chamadas de transcricao pra nao levar IpBlocked do
        # youtube_transcript_api (rajada de requisicoes na mesma rede/IP).
        if i > 0 and not modo_demo and delay:
            time.sleep(delay)

        store.marcar_descoberto(v.video_id, cid, dom, v.published_at, v.title,
                                v.view_count, v.like_count, v.comment_count,
                                v.category_id)
        max_pub = max(max_pub, v.published_at or "")
        novos += 1

        trechos = extrair_transcricao(
            v.video_id, glob_cfg.get("idiomas_legenda", ["pt", "en"]),
            vocab, modo_demo)
        if not trechos:
            store.marcar_falha(v.video_id, "sem legenda")
            falhas += 1
            continue

        texto_total = " ".join(t["text"] for t in trechos)
        h = content_hash(texto_total)
        if store.ja_ingerido(v.video_id, h):   # IDEMPOTENCIA
            pulados += 1
            continue
        try:
            _persistir_bronze(trechos, dom, v.video_id)   # captura crua, sempre
            df = _bronze_silver(v.video_id, trechos)
            _persistir(df, dom, v.video_id)
            store.marcar_ingerido(v.video_id, h, len(df))
            ingeridos += 1
        except (pa.errors.SchemaError, Exception) as e:
            store.marcar_falha(v.video_id, e)
            falhas += 1

    if novos:
        store.update_watermark(cid, max_pub, ingeridos)
    _gold(dom, sinais_pos, sinais_neg, store)

    res = {"canal": canal["nome"], "descobertos": novos, "ingeridos": ingeridos,
           "pulados_idempotencia": pulados, "falhas": falhas,
           "descartados_duracao": descartados_duracao}
    log.info("ciclo %s -> %s", canal["nome"], res)
    return res
