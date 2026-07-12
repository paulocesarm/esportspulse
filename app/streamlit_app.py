# -*- coding: utf-8 -*-
"""
Dashboard de insights — EsportsPulse.

Lê o GOLD (Parquet, domínio único "esports") e o CONTROLE (SQLite) gerados
pelo ingestor e apresenta 3 análises (ver docs/CARTA_DO_PROJETO.md):
  1. Geral   — visão de mercado, todas as organizações agregadas.
  2. Por Time — intra-organização: tipo de conteúdo, modalidade, resultado
     comentado, engajamento e nuvem de palavras dos comentários.
  3. Cross-Org — comparação entre organizações, normalizada por inscritos.

Rodar local:   streamlit run app/streamlit_app.py
O caminho do lakehouse pode ser sobrescrito com a variável de ambiente DATALAKE_DIR.
"""
from __future__ import annotations

import streamlit as st

from common import PROJETO, injetar_css
from paginas import geral, por_time, cross

st.set_page_config(page_title=PROJETO["nome"], page_icon="📊", layout="wide")
injetar_css()

pg = st.navigation([
    st.Page(geral.render, title="Geral", icon="🌐", url_path="geral", default=True),
    st.Page(por_time.render, title="Por Time", icon="🎮", url_path="por-time"),
    st.Page(cross.render, title="Cross-Org", icon="⚔️", url_path="cross-org"),
])
pg.run()
