# -*- coding: utf-8 -*-
"""Página "Geral" — visão de mercado (todas as organizações agregadas)."""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from common import (
    PROJETO, ORGS, TIPOS, ASSETS,
    carregar_gold, carregar_stats_canais, carregar_metadados, carregar_palavras,
    calcular_resumo, cor_tipo, cor_geral, mapa_cor_org, fmt_num, render_hero, render_marca,
    render_tag_cloud,
)


def render() -> None:
    meta = carregar_metadados()

    col_cabecalho, col_atualizacao = st.columns([5, 2])
    with col_cabecalho:
        render_marca()
        st.title(PROJETO["nome"])
        st.caption(f"Domínio: **{PROJETO['dominio']}**")
    with col_atualizacao:
        # Metadado operacional (quando o ingestor rodou pela última vez) --
        # nao e' um KPI de negocio, entao fica pequeno num canto, nao junto
        # das metricas grandes que o stakeholder realmente acompanha.
        ultima = meta["ultima_ingestao"]
        ultima_fmt = str(ultima)[:19].replace("T", " ") if ultima else "—"
        st.caption(f"Última ingestão (UTC)  \n{ultima_fmt}")

    logos = st.columns(len(ORGS))
    for col, (cid, info) in zip(logos, ORGS.items()):
        caminho = ASSETS / info["logo"]
        if caminho.is_file():
            col.image(str(caminho), width=48)
            col.caption(info["nome"])

    gold = carregar_gold()
    stats_canais = carregar_stats_canais()
    palavras = carregar_palavras()

    c1, c2, c3 = st.columns(3)
    c1.metric("Vídeos ingeridos", meta["ingeridos"])
    c2.metric("Descobertos", meta["descobertos"])
    c3.metric("Em falha", meta["falhas"])

    if not meta["tem_controle"]:
        st.info("⏳ Aguardando a primeira ingestão — rode `python -m ingestor.scheduler --once`.")

    st.divider()

    if gold.empty:
        st.warning("Ainda não há dados no GOLD. Assim que o ingestor rodar, os insights aparecem aqui.")
        return

    resumo = calcular_resumo(gold, stats_canais)

    # --- Hero: maior achado do mercado ------------------------------------ #
    if "alcance_relativo" in resumo.columns and (resumo["alcance_relativo"] > 0).sum() >= 2:
        melhor = resumo["alcance_relativo"].idxmax()
        pior = resumo["alcance_relativo"].idxmin()
        razao = resumo.loc[melhor, "alcance_relativo"] / max(resumo.loc[pior, "alcance_relativo"], 0.01)
        cor_hero = mapa_cor_org().get(melhor, cor_geral())
        render_hero(
            "Achado em destaque",
            f"🎯 {melhor} converte inscritos em audiência "
            f'<span style="color:{cor_hero};">{razao:.0f}× melhor</span> que {pior}',
            f"{melhor} tem {resumo.loc[melhor, 'pct_jogo']:.0f}% do conteúdo sobre o jogo "
            f"(vs. {resumo.loc[pior, 'pct_jogo']:.0f}% em {pior}) e alcança "
            f"{resumo.loc[melhor, 'alcance_relativo']:.2f}% dos seus inscritos por vídeo, em média. "
            f"Ver a aba <b>Cross-Org</b> pra comparação completa.",
            cor_hero,
        )

    # --- KPIs de mercado ---------------------------------------------------- #
    total_views = int(gold["view_count"].sum())
    pct_jogo_mercado = (gold["tipo"] == "jogo").mean() * 100
    engajamento_medio = ((gold["like_count"] + gold["comment_count"]).sum()
                         / gold["view_count"].sum() * 100) if gold["view_count"].sum() else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Vídeos no mercado", fmt_num(len(gold)))
    k2.metric("Views somadas", fmt_num(total_views))
    k3.metric("% conteúdo sobre o jogo", f"{pct_jogo_mercado:.0f}%")
    k4.metric("Taxa de engajamento média", f"{engajamento_medio:.2f}%",
             help="(likes + comentários) ÷ views, somado no mercado inteiro")

    st.divider()

    col_mix, col_rank = st.columns([1, 1])

    with col_mix:
        st.subheader("Mix de conteúdo do mercado")
        mix = (gold.assign(total=1).groupby("tipo")["total"].sum().reindex(TIPOS).fillna(0)
              .reset_index())
        mix["pct"] = mix["total"] / mix["total"].sum() * 100
        mix["grupo"] = "Mercado"
        chart_mix = (
            alt.Chart(mix)
            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=32)
            .encode(
                x=alt.X("pct:Q", title="% dos vídeos", stack="zero"),
                y=alt.Y("grupo:N", title=None, axis=None),  # linha unica (barra horizontal)
                color=alt.Color("tipo:N", sort=TIPOS,
                                scale=alt.Scale(domain=TIPOS, range=[cor_tipo(t) for t in TIPOS]),
                                legend=alt.Legend(title="Tipo", orient="bottom")),
                tooltip=[alt.Tooltip("tipo:N", title="Tipo"),
                        alt.Tooltip("total:Q", title="Vídeos"),
                        alt.Tooltip("pct:Q", title="% do mercado", format=".1f")],
            ).properties(height=90)
        )
        st.altair_chart(chart_mix, width="stretch")
        st.caption("Proporção jogo × entretenimento somando todas as organizações monitoradas.")

    with col_rank:
        st.subheader("Prévia — alcance relativo por organização")
        if "alcance_relativo" in resumo.columns:
            ranking = resumo.reset_index().rename(columns={"index": "organizacao"}) \
                            .sort_values("alcance_relativo", ascending=False)
            cores = mapa_cor_org()
            chart_rank = (
                alt.Chart(ranking)
                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=22)
                .encode(
                    y=alt.Y("organizacao:N", title=None, sort="-x"),
                    x=alt.X("alcance_relativo:Q", title="alcance relativo (%)"),
                    color=alt.Color("organizacao:N", scale=alt.Scale(
                        domain=list(cores.keys()), range=list(cores.values())), legend=None),
                    tooltip=[alt.Tooltip("organizacao:N", title="Organização"),
                            alt.Tooltip("alcance_relativo:Q", title="Alcance relativo (%)", format=".2f")],
                # altura escala com a qtd. de organizacoes -- fixo em 140 cortava
                # barras/rotulos (size=22) quando MIBR/Fluxo entraram (3 -> 5).
                ).properties(height=30 + 32 * len(ranking))
            )
            texto_rank = chart_rank.mark_text(align="left", dx=4).encode(
                text=alt.Text("alcance_relativo:Q", format=".2f"))
            st.altair_chart(chart_rank + texto_rank, width="stretch")
            st.caption("Views médias ÷ inscritos — versão completa na aba **Cross-Org**.")
        else:
            st.info("Estatísticas de canal (inscritos) ainda não coletadas.")

    st.divider()

    # --- Timeline de publicacao --------------------------------------------- #
    st.subheader("Cadência de publicação do mercado")
    serie = gold.copy()
    serie["published_at"] = pd.to_datetime(serie["published_at"], errors="coerce", utc=True)
    serie = serie.dropna(subset=["published_at"])
    if not serie.empty:
        semanal = (serie.set_index("published_at").resample("W")["video_id"].count()
                  .rename("videos").reset_index())
        cor_tempo = cor_geral()
        chart_tempo = (
            alt.Chart(semanal)
            .mark_area(opacity=0.12, color=cor_tempo, line={"color": cor_tempo, "size": 2})
            .encode(
                x=alt.X("published_at:T", title=None),
                y=alt.Y("videos:Q", title="vídeos publicados / semana"),
                tooltip=[alt.Tooltip("published_at:T", title="Semana de"),
                        alt.Tooltip("videos:Q", title="Vídeos")],
            ).properties(height=220)
        )
        st.altair_chart(chart_tempo, width="stretch")
    else:
        st.caption("Sem datas de publicação suficientes pra montar a linha do tempo.")

    st.divider()

    # --- Nuvem de palavras global -------------------------------------------- #
    st.subheader("O que a torcida está comentando")
    st.caption("Nuvem de palavras a partir de uma amostra dos comentários mais relevantes "
              "de todos os vídeos monitorados (todas as organizações).")
    if not palavras.empty:
        agregada = palavras.groupby("palavra")["contagem"].sum().reset_index()
        render_tag_cloud(agregada)
    else:
        render_tag_cloud(palavras)

    with st.expander("Sobre os dados"):
        st.markdown(f"**Problema.** {PROJETO['problema']}")
        st.markdown(f"**Propósito.** {PROJETO['proposito']}")
        st.markdown(
            "**Limitações conhecidas:** `view_count`/`like_count`/comentários são um "
            "snapshot do momento da coleta (não atualizam depois); a nuvem de palavras "
            "usa uma amostra dos comentários mais relevantes, não o total; audience "
            "retention/tempo assistido não está disponível publicamente pra canal de "
            "terceiro (só via OAuth do dono do canal)."
        )
