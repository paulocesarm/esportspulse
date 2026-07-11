# -*- coding: utf-8 -*-
"""
Dashboard de insights — template do trabalho final.

Lê o GOLD (Parquet particionado) e o CONTROLE (SQLite) gerados pelo ingestor e
apresenta os insights para o público de negócio definido na Carta do Projeto.

Cada grupo DEVE customizar:
  - o cabeçalho (PROJETO) com nome, problema e propósito da sua Carta;
  - o KPI em destaque (§5 do contrato);
  - as visualizações, ligadas às perguntas analíticas do domínio.

Rodar local:   streamlit run app/streamlit_app.py
O caminho do lakehouse pode ser sobrescrito com a variável de ambiente DATALAKE_DIR.
"""
from __future__ import annotations

import os
import glob
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Configuração do grupo — EDITAR conforme a Carta do Projeto
# --------------------------------------------------------------------------- #
PROJETO = {
    "nome": "EsportsPulse",
    "dominio": "esports (cs2 / valorant / lol)",
    "problema": "Os canais das organizações de esports são majoritariamente vlogs de "
                "bastidor, sem métrica que diga se vídeo comentando vitória, derrota ou "
                "sem menção ao resultado (puro vlog) performa diferente em audiência.",
    "proposito": "Classificar cada vídeo pelo resultado comentado (vitória/derrota/sem "
                 "menção) e cruzar com métricas reais de audiência (views, likes, "
                 "comentários), pra saber que tipo de conteúdo engaja mais.",
    "publico": "Organizações de esports (mídia, conteúdo e comunicação).",
    "kpi_label": "Views médias — vitória vs. derrota vs. sem menção",
}

DATALAKE = Path(os.environ.get("DATALAKE_DIR", "./datalake"))
GOLD_GLOB = str(DATALAKE / "gold" / "**" / "*.parquet")
CONTROL_DB = DATALAKE / "control" / "ingestion.db"


# --------------------------------------------------------------------------- #
# Leitura de dados (com degradação elegante quando ainda não há dados)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=60)
def carregar_gold() -> pd.DataFrame:
    arquivos = glob.glob(GOLD_GLOB, recursive=True)
    if not arquivos:
        return pd.DataFrame()
    frames = []
    for f in arquivos:
        try:
            df = pd.read_parquet(f)
            # deriva o domínio a partir do caminho particionado dominio=<x>
            for parte in Path(f).parts:
                if parte.startswith("dominio="):
                    df["dominio"] = parte.split("=", 1)[1]
            frames.append(df)
        except Exception:
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@st.cache_data(ttl=60)
def carregar_metadados() -> dict:
    """Metadados de confiabilidade a partir do SQLite de controle (§5)."""
    meta = {"ultima_ingestao": None, "ingeridos": 0, "falhas": 0,
            "descobertos": 0, "tem_controle": False}
    if not CONTROL_DB.exists():
        return meta
    try:
        con = sqlite3.connect(str(CONTROL_DB))
        con.row_factory = sqlite3.Row
        meta["tem_controle"] = True
        por_status = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) n FROM ingestion_state GROUP BY status")}
        meta["ingeridos"] = por_status.get("INGESTED", 0)
        meta["falhas"] = por_status.get("FAILED", 0)
        meta["descobertos"] = sum(por_status.values())
        row = con.execute(
            "SELECT MAX(ingested_at) u FROM ingestion_state WHERE status='INGESTED'"
        ).fetchone()
        meta["ultima_ingestao"] = row["u"] if row else None
        con.close()
    except Exception:
        pass
    return meta


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
st.set_page_config(page_title=PROJETO["nome"], page_icon="📊", layout="wide")

st.title(f"📊 {PROJETO['nome']}")
st.caption(f"Domínio: **{PROJETO['dominio']}**  ·  Público-alvo: {PROJETO['publico']}")

with st.expander("Sobre o projeto", expanded=True):
    st.markdown(f"**Problema.** {PROJETO['problema']}")
    st.markdown(f"**Propósito.** {PROJETO['proposito']}")

meta = carregar_metadados()
gold = carregar_gold()

# --- Metadados de confiabilidade (§5) --------------------------------------- #
c1, c2, c3, c4 = st.columns(4)
c1.metric("Vídeos ingeridos", meta["ingeridos"])
c2.metric("Descobertos", meta["descobertos"])
c3.metric("Em falha/quarentena", meta["falhas"])
ultima = meta["ultima_ingestao"] or "—"
c4.metric("Última ingestão (UTC)", str(ultima)[:19].replace("T", " "))

if not meta["tem_controle"]:
    st.info("⏳ Aguardando a primeira ingestão — o controle (SQLite) ainda não existe. "
            "Rode o ingestor (`python -m ingestor.scheduler --once`) para popular o lakehouse.")

st.divider()

# --- KPI em destaque + visualizações ---------------------------------------- #
if gold.empty:
    st.warning("Ainda não há dados no GOLD. Assim que o ingestor rodar, os insights aparecem aqui.")
    st.stop()

# Gold: video_id, categoria (resultado_positivo/resultado_negativo/sem_resultado),
# trechos_total, view_count, like_count, comment_count, category_id, title, dominio
# — 1 linha por vídeo, cruzando classificação de conteúdo com audiência real.
CATEGORIAS = ["resultado_positivo", "resultado_negativo", "sem_resultado"]
ROTULOS = {"resultado_positivo": "Vitória", "resultado_negativo": "Derrota",
          "sem_resultado": "Sem menção (vlog puro)"}
schema_esperado = {"video_id", "categoria", "view_count"}.issubset(gold.columns)

if schema_esperado:
    gold["view_count"] = pd.to_numeric(gold["view_count"], errors="coerce").fillna(0)
    gold["like_count"] = pd.to_numeric(gold["like_count"], errors="coerce").fillna(0)
    gold["comment_count"] = pd.to_numeric(gold["comment_count"], errors="coerce").fillna(0)

    por_categoria = (gold.groupby("categoria")[["view_count", "like_count", "comment_count"]]
                     .mean().reindex(CATEGORIAS).fillna(0))
    n_videos = gold.groupby("categoria").size().reindex(CATEGORIAS).fillna(0).astype(int)

    k1, k2 = st.columns([1, 2])
    with k1:
        for cat in CATEGORIAS:
            st.metric(f"Views médias — {ROTULOS[cat]}",
                     f"{por_categoria.loc[cat, 'view_count']:,.0f}".replace(",", "."),
                     help=f"{n_videos[cat]} vídeo(s) nessa categoria")
    with k2:
        st.subheader("Views médias por categoria de resultado")
        st.bar_chart(por_categoria["view_count"].rename(index=ROTULOS))

    st.subheader("Engajamento detalhado por categoria")
    tabela_resumo = por_categoria.rename(index=ROTULOS).copy()
    tabela_resumo.insert(0, "n_videos", n_videos.rename(index=ROTULOS))
    st.dataframe(tabela_resumo, use_container_width=True)

    st.subheader("Vídeos por audiência (detalhe)")
    cols_show = ["dominio", "video_id", "title", "categoria", "view_count",
                "like_count", "comment_count", "category_id"]
    cols_show = [c for c in cols_show if c in gold.columns]
    st.dataframe(
        gold[cols_show].sort_values("view_count", ascending=False).head(20),
        use_container_width=True, hide_index=True)

    # Download de amostra do Gold (sugestão pontuável — §5)
    st.download_button("⬇️ Baixar amostra do Gold (CSV)",
                       data=gold.to_csv(index=False).encode("utf-8"),
                       file_name="gold_amostra.csv", mime="text/csv")
else:
    # Gold customizado com outro esquema: mostra o que houver, sem quebrar.
    st.subheader("Gold do domínio")
    st.dataframe(gold, use_container_width=True, hide_index=True)
    st.info("Gold com esquema inesperado — confira pipeline._gold().")

st.divider()
st.caption("Como interpretar: cada vídeo é classificado pelo resultado que comenta "
           "(vitória, derrota, ou sem menção — puro vlog de bastidor) e cruzado com "
           "métricas reais de audiência. Use para responder se vídeo de vitória/derrota "
           "engaja mais que vlog aleatório, e para comparar canais.")
