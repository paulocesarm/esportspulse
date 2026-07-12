# -*- coding: utf-8 -*-
"""Página "Por Time" — análise intra-canal de uma organização selecionada."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from common import (
    ASSETS, TIPOS, CATEGORIAS_RESULTADO, ROTULOS_RESULTADO, JOGOS_LABEL,
    carregar_gold, carregar_stats_canais, carregar_palavras,
    cor_tipo, cor_status, cor_jogo, channel_id_por_nome, logo_path, fmt_num,
    nota_org, render_tag_cloud,
)


def render() -> None:
    st.title("🎮 Por Time")

    gold = carregar_gold()
    if gold.empty:
        st.warning("Ainda não há dados no GOLD. Assim que o ingestor rodar, os insights aparecem aqui.")
        return

    stats_canais = carregar_stats_canais()
    palavras = carregar_palavras()

    orgs_disp = sorted(gold["organizacao"].unique())
    org_sel = st.selectbox("Organização", orgs_disp, key="por_time_org")
    cid_sel = channel_id_por_nome(org_sel)

    cabecalho, inscritos_col = st.columns([3, 1])
    with cabecalho:
        caminho = logo_path(cid_sel) if cid_sel else None
        if caminho:
            lg, tt = st.columns([1, 8])
            lg.image(caminho, width=48)
            tt.markdown(f"### {org_sel}")
        else:
            st.markdown(f"### {org_sel}")
        nota = nota_org(cid_sel) if cid_sel else None
        if nota:
            st.caption(nota)
    if not stats_canais.empty and cid_sel:
        linha = stats_canais[stats_canais["channel_id"] == cid_sel]
        if not linha.empty:
            inscritos_col.metric("Inscritos", fmt_num(linha["subscriber_count"].iloc[0]))

    dgold = gold[gold["organizacao"] == org_sel]

    pct_jogo = (dgold["tipo"] == "jogo").mean() * 100
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Vídeos", fmt_num(len(dgold)))
    k2.metric("% sobre o jogo", f"{pct_jogo:.0f}%")
    k3.metric("Views médias", fmt_num(dgold["view_count"].mean()))
    k4.metric("Likes / comentários médios",
             f"{fmt_num(dgold['like_count'].mean())} / {fmt_num(dgold['comment_count'].mean())}")

    st.divider()

    col_tipo, col_modalidade = st.columns(2)

    with col_tipo:
        st.subheader("Tipo de conteúdo × engajamento")
        por_tipo = (dgold.groupby("tipo")[["view_count", "like_count", "comment_count"]]
                   .mean().reindex(TIPOS).fillna(0)).reset_index()
        n_tipo = dgold.groupby("tipo").size().reindex(TIPOS).fillna(0).astype(int)
        por_tipo["n_videos"] = por_tipo["tipo"].map(n_tipo)
        chart_tipo = (
            alt.Chart(por_tipo)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=32)
            .encode(
                x=alt.X("tipo:N", title=None, sort=TIPOS, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("view_count:Q", title="views médias"),
                color=alt.Color("tipo:N", scale=alt.Scale(domain=TIPOS,
                                range=[cor_tipo(t) for t in TIPOS]), legend=None),
                tooltip=[alt.Tooltip("tipo:N", title="Tipo"),
                        alt.Tooltip("n_videos:Q", title="Vídeos"),
                        alt.Tooltip("view_count:Q", title="Views médias", format=",.0f")],
            ).properties(height=240)
        )
        texto_tipo = chart_tipo.mark_text(dy=-8).encode(text=alt.Text("view_count:Q", format=",.0f"))
        st.altair_chart(chart_tipo + texto_tipo, width="stretch")

    with col_modalidade:
        st.subheader("Modalidade mencionada")
        mix_jogo = (dgold.groupby("jogo_detectado").size().rename("videos").reset_index())
        mix_jogo["rotulo"] = mix_jogo["jogo_detectado"].map(JOGOS_LABEL).fillna(mix_jogo["jogo_detectado"])
        cores_jogo = {row["rotulo"]: cor_jogo(row["jogo_detectado"]) for _, row in mix_jogo.iterrows()}
        chart_jogo = (
            alt.Chart(mix_jogo)
            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=26)
            .encode(
                y=alt.Y("rotulo:N", title=None, sort="-x"),
                x=alt.X("videos:Q", title="vídeos"),
                color=alt.Color("rotulo:N", scale=alt.Scale(
                    domain=list(cores_jogo.keys()), range=list(cores_jogo.values())), legend=None),
                tooltip=[alt.Tooltip("rotulo:N", title="Modalidade"),
                        alt.Tooltip("videos:Q", title="Vídeos")],
            ).properties(height=240)
        )
        st.altair_chart(chart_jogo, width="stretch")
        st.caption("Detectada na própria transcrição do vídeo — um canal institucional cobre "
                  "várias modalidades.")

    jogo_df = dgold[dgold["tipo"] == "jogo"]
    if not jogo_df.empty:
        st.divider()
        st.subheader("Dentro dos vídeos sobre o jogo: resultado comentado")
        por_resultado = (jogo_df.groupby("categoria")[["view_count", "like_count", "comment_count"]]
                        .mean().reindex(CATEGORIAS_RESULTADO).fillna(0)).reset_index()
        n_resultado = jogo_df.groupby("categoria").size().reindex(CATEGORIAS_RESULTADO).fillna(0).astype(int)
        por_resultado["rotulo"] = por_resultado["categoria"].map(ROTULOS_RESULTADO)
        por_resultado["n_videos"] = por_resultado["categoria"].map(n_resultado)

        rc1, rc2 = st.columns([2, 1])
        with rc1:
            chart_resultado = (
                alt.Chart(por_resultado)
                .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=32)
                .encode(
                    x=alt.X("rotulo:N", title=None, sort=[ROTULOS_RESULTADO[c] for c in CATEGORIAS_RESULTADO],
                           axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("view_count:Q", title="views médias"),
                    color=alt.Color("categoria:N",
                                    scale=alt.Scale(domain=CATEGORIAS_RESULTADO,
                                                    range=[cor_status(c) for c in CATEGORIAS_RESULTADO]),
                                    legend=alt.Legend(title="Resultado", labelExpr="datum.label")),
                    tooltip=[alt.Tooltip("rotulo:N", title="Resultado"),
                            alt.Tooltip("n_videos:Q", title="Vídeos"),
                            alt.Tooltip("view_count:Q", title="Views médias", format=",.0f")],
                ).properties(height=260)
            )
            st.altair_chart(chart_resultado, width="stretch")
        with rc2:
            tabela = por_resultado.set_index("rotulo")[["n_videos", "view_count", "like_count", "comment_count"]]
            st.dataframe(tabela, width="stretch")

    st.divider()
    st.subheader(f"Views vs. curtidas — {org_sel}")
    st.caption("Cada ponto é um vídeo; a cor mostra o resultado comentado (ou o tipo, se não for sobre o jogo).")
    dgold_plot = dgold.copy()
    dgold_plot["rotulo_cor"] = dgold_plot.apply(
        lambda r: ROTULOS_RESULTADO.get(r["categoria"], "Entretenimento") if r["tipo"] == "jogo"
        else "Entretenimento", axis=1)
    dominio_cor = [ROTULOS_RESULTADO[c] for c in CATEGORIAS_RESULTADO] + ["Entretenimento"]
    range_cor = [cor_status(c) for c in CATEGORIAS_RESULTADO] + [cor_tipo("entretenimento")]
    scatter = (
        alt.Chart(dgold_plot)
        .mark_circle(size=110, opacity=0.85)
        .encode(
            x=alt.X("view_count:Q", title="views"),
            y=alt.Y("like_count:Q", title="curtidas"),
            color=alt.Color("rotulo_cor:N", scale=alt.Scale(domain=dominio_cor, range=range_cor),
                            legend=alt.Legend(title="Categoria")),
            tooltip=[alt.Tooltip("title:N", title="Vídeo"),
                    alt.Tooltip("view_count:Q", title="Views", format=",.0f"),
                    alt.Tooltip("like_count:Q", title="Curtidas", format=",.0f"),
                    alt.Tooltip("rotulo_cor:N", title="Categoria")],
        ).properties(height=300)
    )
    st.altair_chart(scatter, width="stretch")

    st.subheader(f"Vídeos de {org_sel} por audiência")
    tabela_videos = dgold.copy()
    tabela_videos["modalidade"] = tabela_videos["jogo_detectado"].map(JOGOS_LABEL).fillna(tabela_videos["jogo_detectado"])
    cols_show = ["title", "tipo", "categoria", "modalidade", "view_count",
                "like_count", "comment_count", "category_id"]
    cols_show = [c for c in cols_show if c in tabela_videos.columns]
    tabela_videos = tabela_videos[cols_show].sort_values("view_count", ascending=False).copy()
    if "categoria" in tabela_videos.columns:
        tabela_videos["categoria"] = tabela_videos["categoria"].map(
            lambda c: ROTULOS_RESULTADO.get(c, "—" if c == "" else c))
    st.dataframe(tabela_videos, width="stretch", hide_index=True)

    st.divider()
    st.subheader(f"O que a torcida de {org_sel} está comentando")
    st.caption("Nuvem de palavras a partir de uma amostra dos comentários mais relevantes deste time.")
    if not palavras.empty and cid_sel:
        do_time = palavras[palavras["channel_id"] == cid_sel]
        render_tag_cloud(do_time)
    else:
        render_tag_cloud(pd.DataFrame())
