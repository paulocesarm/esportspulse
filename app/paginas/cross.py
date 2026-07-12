# -*- coding: utf-8 -*-
"""Página "Cross-Org" — comparação entre organizações."""
from __future__ import annotations

import altair as alt
import streamlit as st

from common import (
    TIPOS, ROTULOS_RESULTADO, JOGOS_LABEL,
    carregar_gold, carregar_stats_canais,
    calcular_resumo, cor_tipo, cor_jogo, cor_status, mapa_cor_org,
    logo_data_uri, channel_id_por_nome,
)


def render() -> None:
    st.title("⚔️ Cross-Org")
    st.caption("Comparação entre organizações — normalizada por inscritos, pra "
              "não distorcer entre canais de audiência muito diferente.")

    gold = carregar_gold()
    if gold.empty:
        st.warning("Ainda não há dados no GOLD. Assim que o ingestor rodar, os insights aparecem aqui.")
        return

    stats_canais = carregar_stats_canais()
    resumo = calcular_resumo(gold, stats_canais)
    cores = mapa_cor_org()

    rank_a, rank_b = st.columns(2)

    with rank_a:
        st.subheader("Alcance relativo")
        st.caption("Views médias ÷ inscritos × 100 — quem converte melhor a base em audiência.")
        if "alcance_relativo" in resumo.columns:
            ranking = resumo.reset_index().rename(columns={"index": "organizacao"}) \
                            .sort_values("alcance_relativo", ascending=False)
            chart = (
                alt.Chart(ranking)
                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=24)
                .encode(
                    y=alt.Y("organizacao:N", title=None, sort="-x"),
                    x=alt.X("alcance_relativo:Q", title="alcance relativo (%)"),
                    color=alt.Color("organizacao:N", scale=alt.Scale(
                        domain=list(cores.keys()), range=list(cores.values())), legend=None),
                    tooltip=[alt.Tooltip("organizacao:N", title="Organização"),
                            alt.Tooltip("alcance_relativo:Q", title="Alcance relativo (%)", format=".2f"),
                            alt.Tooltip("subscriber_count:Q", title="Inscritos", format=",.0f")],
                # altura escala com a qtd. de organizacoes -- fixo em 160 cortava
                # barras (size=24) quando MIBR/Fluxo entraram e passou de 3 pra 5.
                ).properties(height=40 + 34 * len(ranking))
            )
            texto = chart.mark_text(align="left", dx=4).encode(
                text=alt.Text("alcance_relativo:Q", format=".2f"))
            st.altair_chart(chart + texto, width="stretch")
        else:
            st.info("Estatísticas de canal (inscritos) ainda não coletadas.")

    with rank_b:
        st.subheader("Taxa de engajamento")
        st.caption("(likes + comentários) ÷ views × 100 — o quanto quem viu interagiu.")
        ranking_eng = resumo.reset_index().rename(columns={"index": "organizacao"}) \
                            .sort_values("taxa_engajamento", ascending=False)
        chart_eng = (
            alt.Chart(ranking_eng)
            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=24)
            .encode(
                y=alt.Y("organizacao:N", title=None, sort="-x"),
                x=alt.X("taxa_engajamento:Q", title="taxa de engajamento (%)"),
                color=alt.Color("organizacao:N", scale=alt.Scale(
                    domain=list(cores.keys()), range=list(cores.values())), legend=None),
                tooltip=[alt.Tooltip("organizacao:N", title="Organização"),
                        alt.Tooltip("taxa_engajamento:Q", title="Taxa de engajamento (%)", format=".2f")],
            ).properties(height=40 + 34 * len(ranking_eng))
        )
        texto_eng = chart_eng.mark_text(align="left", dx=4).encode(
            text=alt.Text("taxa_engajamento:Q", format=".2f"))
        st.altair_chart(chart_eng + texto_eng, width="stretch")

    st.divider()

    col_tipo, col_modalidade = st.columns(2)

    with col_tipo:
        st.subheader("Mix de conteúdo por organização")
        mix = (gold.groupby(["organizacao", "tipo"]).size().rename("videos").reset_index())
        chart_mix = (
            alt.Chart(mix)
            .mark_bar(size=32)
            .encode(
                x=alt.X("organizacao:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("videos:Q", title="qtd. de vídeos", stack="normalize"),
                color=alt.Color("tipo:N", scale=alt.Scale(domain=TIPOS,
                                range=[cor_tipo(t) for t in TIPOS]), legend=alt.Legend(title="Tipo")),
                tooltip=[alt.Tooltip("organizacao:N", title="Organização"),
                        alt.Tooltip("tipo:N", title="Tipo"),
                        alt.Tooltip("videos:Q", title="Vídeos")],
            ).properties(height=280)
        )
        st.altair_chart(chart_mix, width="stretch")

    with col_modalidade:
        st.subheader("Onde cada time foca conteúdo (modalidade)")
        mix_jogo = (gold.assign(rotulo=gold["jogo_detectado"].map(JOGOS_LABEL).fillna(gold["jogo_detectado"]))
                   .groupby(["organizacao", "rotulo"]).size().rename("videos").reset_index())
        jogos_presentes = sorted(mix_jogo["rotulo"].unique())
        cores_jogo = {r: cor_jogo(j) for j, r in JOGOS_LABEL.items() if r in jogos_presentes}
        chart_modalidade = (
            alt.Chart(mix_jogo)
            .mark_bar(size=32)
            .encode(
                x=alt.X("organizacao:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("videos:Q", title="qtd. de vídeos", stack="normalize"),
                color=alt.Color("rotulo:N", scale=alt.Scale(
                    domain=list(cores_jogo.keys()), range=list(cores_jogo.values())),
                    legend=alt.Legend(title="Modalidade")),
                tooltip=[alt.Tooltip("organizacao:N", title="Organização"),
                        alt.Tooltip("rotulo:N", title="Modalidade"),
                        alt.Tooltip("videos:Q", title="Vídeos")],
            ).properties(height=280)
        )
        st.altair_chart(chart_modalidade, width="stretch")
        st.caption("Modalidade detectada na transcrição de cada vídeo — não é fixa por canal.")

    st.divider()

    # --- Vitoria x derrota entre orgs qualificadas -------------------------- #
    st.subheader("Vitória × derrota entre organizações")
    jogo_gold = gold[gold["tipo"] == "jogo"]
    tem_ambas = (jogo_gold.groupby("organizacao")["categoria"]
                .apply(lambda s: {"resultado_positivo", "resultado_negativo"}.issubset(set(s))))
    qualificadas = sorted(tem_ambas[tem_ambas].index)
    excluidas = sorted(set(gold["organizacao"].unique()) - set(qualificadas))

    if qualificadas:
        comparativo = (jogo_gold[jogo_gold["organizacao"].isin(qualificadas)
                                 & jogo_gold["categoria"].isin(["resultado_positivo", "resultado_negativo"])]
                      .groupby(["organizacao", "categoria"])[["view_count", "like_count", "comment_count"]]
                      .mean().reset_index())
        comparativo["rotulo"] = comparativo["categoria"].map(ROTULOS_RESULTADO)
        chart_vd = (
            alt.Chart(comparativo)
            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=18)
            .encode(
                y=alt.Y("organizacao:N", title=None),
                x=alt.X("view_count:Q", title="views médias"),
                yOffset=alt.YOffset("categoria:N", sort=["resultado_positivo", "resultado_negativo"]),
                color=alt.Color("categoria:N", scale=alt.Scale(
                    domain=["resultado_positivo", "resultado_negativo"],
                    range=[cor_status("resultado_positivo"), cor_status("resultado_negativo")]),
                    legend=alt.Legend(title="Resultado", labelExpr="datum.label")),
                tooltip=[alt.Tooltip("organizacao:N", title="Organização"),
                        alt.Tooltip("rotulo:N", title="Resultado"),
                        alt.Tooltip("view_count:Q", title="Views médias", format=",.0f")],
            ).properties(height=90 + 60 * len(qualificadas))
        )
        st.altair_chart(chart_vd, width="stretch")
    else:
        st.info("Nenhuma organização tem, ainda, vídeos de vitória **e** derrota comentados "
               "em volume suficiente pra essa comparação — precisa de pelo menos 1 vídeo de "
               "cada resultado por organização.")
    if excluidas:
        st.caption(f"Fora dessa comparação: {', '.join(excluidas)} — ainda sem as duas "
                  "categorias de resultado.")

    st.divider()

    st.subheader("Resumo comparativo entre organizações")
    resumo_show = resumo.reset_index().rename(columns={"index": "organizacao"})
    resumo_show["logo"] = resumo_show["organizacao"].map(
        lambda n: logo_data_uri(channel_id_por_nome(n)))
    colunas_cfg = {
        "logo": st.column_config.ImageColumn("Logo", width="small"),
        "n_videos": st.column_config.NumberColumn("Vídeos"),
        "pct_jogo": st.column_config.NumberColumn("% jogo", format="%.0f%%"),
        "views_medias": st.column_config.NumberColumn("Views médias", format="%.0f"),
        "likes_medios": st.column_config.NumberColumn("Likes médios", format="%.0f"),
        "comentarios_medios": st.column_config.NumberColumn("Comentários médios", format="%.0f"),
        "subscriber_count": st.column_config.NumberColumn("Inscritos", format="%.0f"),
        "alcance_relativo": st.column_config.NumberColumn("Alcance relativo (%)", format="%.2f"),
        "taxa_engajamento": st.column_config.NumberColumn("Taxa de engajamento (%)", format="%.2f"),
    }
    ordem_cols = ["logo", "n_videos", "pct_jogo", "views_medias", "likes_medios",
                 "comentarios_medios", "subscriber_count", "alcance_relativo", "taxa_engajamento"]
    ordem_cols = [c for c in ordem_cols if c in resumo_show.columns]
    st.dataframe(resumo_show.set_index("organizacao")[ordem_cols], width="stretch",
                column_config=colunas_cfg)

    st.download_button("⬇️ Baixar amostra do Gold (CSV)",
                       data=gold.to_csv(index=False).encode("utf-8"),
                       file_name="gold_amostra.csv", mime="text/csv")
