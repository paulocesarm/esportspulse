# -*- coding: utf-8 -*-
"""
Constantes, loaders de dados e helpers de UI compartilhados pelas 3 paginas
do dashboard (app/paginas/geral.py, por_time.py, cross.py).

Paleta: segue a skill dataviz (references/palette.md) -- oito matizes fixos,
validados por node scripts/validate_palette.js (CVD/contraste/luminancia),
com par claro/escuro por matiz (o par escuro nao e um auto-invert, e um passo
prorio calibrado pra superficie escura). Cada dimensao categorica (org, tipo
de conteudo, modalidade, resultado) usa uma fatia FIXA e nunca ciclada desses
oito matizes -- nunca reaproveita o mesmo matiz dentro da MESMA dimensao.
"""
from __future__ import annotations

import base64
import glob
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

# pandas 3.x + pyarrow novo tem SEGFAULT real em .isna()/.fillna()/.astype()
# quando a coluna e 100% nula (ex.: "categoria" pra vídeo tipo=entretenimento)
# -- ver requirements.txt. Isso volta pro dtype 'object' classico.
pd.set_option("future.infer_string", False)

DATALAKE = Path(__import__("os").environ.get("DATALAKE_DIR", "./datalake"))
GOLD_GLOB = str(DATALAKE / "gold" / "dominio=esports" / "*.parquet")
CONTROL_DB = DATALAKE / "control" / "ingestion.db"
ASSETS = Path(__file__).parent / "assets"

PROJETO = {
    "nome": "EsportsPulse",
    "dominio": "esports (institucional — CS2 / Valorant / LoL / Free Fire / R6, detectado por vídeo)",
    "problema": "Os canais oficiais das organizações de esports misturam conteúdo sobre "
                "o jogo (torneio, partida) com entretenimento genérico sem relação "
                "nenhuma com o jogo, e cobrem várias modalidades no mesmo canal "
                "institucional — não há visão de que tipo de conteúdo, nem qual "
                "modalidade, realmente engaja, tanto dentro de uma organização "
                "quanto no mercado como um todo.",
    "proposito": "Classificar cada vídeo por tipo (jogo vs. entretenimento), pela "
                 "modalidade mencionada (detectada na própria transcrição) e, quando "
                 "for sobre o jogo, pelo resultado comentado (vitória/derrota) — "
                 "cruzando tudo com audiência real e com o texto dos comentários do "
                 "público.",
    "publico": "Organizações de esports (mídia, conteúdo e comunicação).",
}

# --------------------------------------------------------------------------- #
# Paleta — 8 matizes fixos (skill dataviz), par claro/escuro por matiz.
# --------------------------------------------------------------------------- #
_PALETA = {
    "azul":     {"light": "#2a78d6", "dark": "#3987e5"},
    "agua":     {"light": "#1baf7a", "dark": "#199e70"},
    "amarelo":  {"light": "#eda100", "dark": "#c98500"},
    "verde":    {"light": "#008300", "dark": "#008300"},
    "violeta":  {"light": "#4a3aa7", "dark": "#9085e9"},
    # dark original (#e66767) era claro/dessaturado demais -- lia como coral/
    # laranja perto do rosa da FURIA (magenta) em vez de vermelho de verdade.
    "vermelho": {"light": "#e34948", "dark": "#ef4444"},
    "magenta":  {"light": "#e87ba4", "dark": "#d55181"},
    "laranja":  {"light": "#eb6834", "dark": "#d95926"},
}
_CINZA_NEUTRO = "#898781"   # so pra "indefinido" -- neutro por design, sempre com rotulo


def tema_ativo() -> str:
    """'dark' ou 'light' -- tema REAL da sessao do usuario (nao config estatica)."""
    try:
        t = st.context.theme.type
        return t if t in ("dark", "light") else "light"
    except Exception:
        return "light"


def _cor(matiz: str) -> str:
    return _PALETA[matiz][tema_ativo()]


# Organizacao (channel_id) -> nome/logo/matiz -- fatia 1..3 (ativos) + 4..5 (inativos)
# "nota" (opcional): esclarecimento sobre o escopo do canal monitorado, exibido
# em Por Time (ver app/paginas/por_time.py). So a FURIA tem: o canal oficial
# monitorado ("FURIA CS", nome que a propria API do YouTube retorna) e
# dedicado a CS2 -- por isso todo o conteudo aqui e dessa modalidade.
#
# "logo": FURIA/MIBR/paiN sao marca solida preta (ou quase) em fundo
# transparente -- somem no tema escuro (padrao do dashboard, ver
# .streamlit/config.toml). Por isso usam a variante "*_chip.png" (mesmo
# logo, com um card claro arredondado assado na propria imagem -- nao e' so
# CSS, porque o logo tambem aparece dentro de st.column_config.ImageColumn
# em cross.py, que nao aceita wrapper de HTML/CSS por cima). LOUD (verde) e
# Fluxo (aneis coloridos + texto branco) ja tem contraste proprio nos dois
# temas, entao usam o arquivo original.
ORGS = {
    # Matiz por org buscando a cor de marca de cada time (aproximada onde a
    # cor real (preto/branco puro da FURIA) não teria contraste no tema
    # escuro padrão do dashboard -- ver comentario de "logo" acima): LOUD
    # verde, paiN vermelho, MIBR azul, Fluxo roxo, FURIA rosa (magenta).
    "UCT1F3iuRk0j7owMzNC09q1w": {"nome": "FURIA eSports", "logo": "furia_chip.png", "matiz": "magenta",
        "nota": "Canal institucional monitorado é o \"FURIA CS\", dedicado a CS2 — "
               "por isso todo o conteúdo desta organização aqui é dessa modalidade."},
    "UC7iwNp4GUynlGXvK-6KD0Rw": {"nome": "LOUD",          "logo": "loud.png",      "matiz": "verde"},
    "UC0jnW-v_1IanHuj2y3Z1AGA": {"nome": "paiN Gaming",   "logo": "pain_chip.png", "matiz": "vermelho"},
    "UCE30pLfsQQWijIN0RYFoESA": {"nome": "MIBR",          "logo": "mibr_chip.png", "matiz": "azul"},
    "UCUSKHWPgQl1ixaal1vysMyw": {"nome": "Fluxo",         "logo": "fluxo.png",     "matiz": "violeta"},
}

TIPOS = ["jogo", "entretenimento"]
COR_TIPO = {"jogo": _PALETA["azul"], "entretenimento": _PALETA["agua"]}

CATEGORIAS_RESULTADO = ["resultado_positivo", "resultado_negativo", "indefinido"]
ROTULOS_RESULTADO = {"resultado_positivo": "Vitória", "resultado_negativo": "Derrota",
                     "indefinido": "Jogo, sem resultado claro"}
COR_STATUS = {"resultado_positivo": _PALETA["verde"], "resultado_negativo": _PALETA["vermelho"],
             "indefinido": {"light": _CINZA_NEUTRO, "dark": _CINZA_NEUTRO}}

JOGOS_LABEL = {"cs2": "CS2", "valorant": "Valorant", "lol": "League of Legends",
              "freefire": "Free Fire", "r6": "Rainbow Six", "indefinido": "Não identificada"}
COR_JOGO = {"cs2": _PALETA["laranja"], "valorant": _PALETA["vermelho"], "lol": _PALETA["violeta"],
           "freefire": _PALETA["magenta"], "r6": _PALETA["verde"],
           "indefinido": {"light": _CINZA_NEUTRO, "dark": _CINZA_NEUTRO}}

TXT_MUTED = "#898781"


def cor_org(channel_id: str) -> str:
    info = ORGS.get(channel_id)
    return _cor(info["matiz"]) if info else _cor("laranja")


def cor_geral() -> str:
    """Cor fixa pros elementos AGREGADOS de mercado (nao quebrados por org),
    ex.: cadencia de publicacao, nuvem de palavras -- laranja pra nao colidir
    com nenhuma cor de organizacao (MIBR e azul, FURIA e magenta/rosa etc)."""
    return _cor("laranja")


def cor_tipo(tipo: str) -> str:
    return COR_TIPO.get(tipo, {}).get(tema_ativo(), _CINZA_NEUTRO)


def cor_status(categoria: str) -> str:
    return COR_STATUS.get(categoria, {}).get(tema_ativo(), _CINZA_NEUTRO)


def cor_jogo(jogo: str) -> str:
    return COR_JOGO.get(jogo, {}).get(tema_ativo(), _CINZA_NEUTRO)


def logo_path(channel_id: str) -> str | None:
    info = ORGS.get(channel_id)
    if not info:
        return None
    p = ASSETS / info["logo"]
    return str(p) if p.is_file() else None


def logo_data_uri(channel_id: str) -> str | None:
    """Logo como data URI (base64) -- necessario pra st.column_config.
    ImageColumn (cross.py): diferente de st.image(), que serve um caminho
    local de arquivo pelo proprio protocolo do Streamlit, a celula de uma
    ImageColumn vira o "src" literal de uma <img> no navegador -- um caminho
    de arquivo absoluto do sistema (`/Users/.../assets/logo.png`) nao resolve
    ali (o navegador nao acessa o filesystem do servidor), e a coluna
    aparecia sempre vazia."""
    p = logo_path(channel_id)
    if not p:
        return None
    ext = Path(p).suffix.lstrip(".") or "png"
    b64 = base64.b64encode(Path(p).read_bytes()).decode()
    return f"data:image/{ext};base64,{b64}"


def nome_org(channel_id: str) -> str:
    info = ORGS.get(channel_id)
    return info["nome"] if info else channel_id


def nota_org(channel_id: str) -> str | None:
    info = ORGS.get(channel_id)
    return info.get("nota") if info else None


def channel_id_por_nome(nome: str) -> str | None:
    for cid, info in ORGS.items():
        if info["nome"] == nome:
            return cid
    return None


def mapa_cor_org() -> dict[str, str]:
    """nome da organizacao -> hex (tema atual) -- pra escala categorica do
    Altair, que colore por 'organizacao' (nome), nao por channel_id."""
    return {info["nome"]: cor_org(cid) for cid, info in ORGS.items()}


# --------------------------------------------------------------------------- #
# Leitura de dados (com degradacao elegante quando ainda nao ha dados)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=60)
def carregar_gold() -> pd.DataFrame:
    arquivos = glob.glob(GOLD_GLOB)
    frames = []
    for f in arquivos:
        if Path(f).name == "palavras_comentarios.parquet":
            continue
        try:
            df = pd.read_parquet(f)
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    gold = pd.concat(frames, ignore_index=True)
    for col in ("view_count", "like_count", "comment_count"):
        gold[col] = pd.to_numeric(gold[col], errors="coerce").fillna(0)
    for col in ("categoria", "title", "category_id", "channel_id", "published_at", "jogo_detectado"):
        if col in gold.columns:
            gold[col] = gold[col].fillna("")
    gold["organizacao"] = gold["channel_id"].map(nome_org).fillna(gold["channel_id"])
    return gold


@st.cache_data(ttl=60)
def carregar_palavras() -> pd.DataFrame:
    """Frequencia de palavra por canal (comentarios reais) -- base da nuvem
    de palavras. Ver ingestor/pipeline.py:_gold_palavras."""
    caminho = DATALAKE / "gold" / "dominio=esports" / "palavras_comentarios.parquet"
    if not caminho.is_file():
        return pd.DataFrame()
    try:
        return pd.read_parquet(caminho)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def carregar_stats_canais() -> pd.DataFrame:
    """Estatisticas de canal (inscritos etc.) -- base da analise cross-org."""
    if not CONTROL_DB.exists():
        return pd.DataFrame()
    try:
        con = sqlite3.connect(str(CONTROL_DB))
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM channel_stats").fetchall()
        con.close()
        df = pd.DataFrame([dict(r) for r in rows])
        if not df.empty:
            df["organizacao"] = df["channel_id"].map(nome_org).fillna(df["channel_id"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def carregar_metadados() -> dict:
    """Metadados de confiabilidade a partir do SQLite de controle."""
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


def fmt_num(v) -> str:
    return f"{v:,.0f}".replace(",", ".")


def calcular_resumo(gold: pd.DataFrame, stats_canais: pd.DataFrame) -> pd.DataFrame:
    """Resumo por organizacao -- base das paginas Geral e Cross-Org: volume,
    mix de conteudo, engajamento medio e (quando ha inscritos) as duas
    metricas normalizadas: alcance relativo (views / inscritos) e taxa de
    engajamento ((likes+comentarios) / views)."""
    resumo = (gold.groupby("organizacao")
             .agg(n_videos=("video_id", "count"),
                  pct_jogo=("tipo", lambda s: (s == "jogo").mean() * 100),
                  views_medias=("view_count", "mean"),
                  likes_medios=("like_count", "mean"),
                  comentarios_medios=("comment_count", "mean"))
             .round(1))
    resumo["taxa_engajamento"] = (
        (resumo["likes_medios"] + resumo["comentarios_medios"])
        / resumo["views_medias"].where(resumo["views_medias"] > 0, float("nan"))
        * 100).round(2).fillna(0.0)

    if not stats_canais.empty:
        inscritos = stats_canais.set_index("organizacao")[["subscriber_count"]]
        resumo = resumo.join(inscritos, how="left")
        resumo["subscriber_count"] = pd.to_numeric(
            resumo["subscriber_count"], errors="coerce").fillna(0.0)
        divisor = resumo["subscriber_count"].where(resumo["subscriber_count"] > 0, float("nan"))
        resumo["alcance_relativo"] = (resumo["views_medias"] / divisor * 100).round(2).fillna(0.0)
    return resumo


# --------------------------------------------------------------------------- #
# Helpers de UI
# --------------------------------------------------------------------------- #
def injetar_css() -> None:
    st.markdown("""
<style>
.ep-card {
    border: 1px solid rgba(137,135,129,0.28);
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
}
.ep-hero {
    border-left: 6px solid #eb6834;
    background: rgba(137,135,129,0.08);
    border-radius: 8px;
    padding: 18px 22px;
    margin-bottom: 14px;
}
.ep-hero-kicker {
    font-size: 0.78rem; letter-spacing: .07em; text-transform: uppercase;
    color: #898781; font-weight: 600;
}
.ep-hero-titulo { font-size: 1.2rem; font-weight: 700; margin-top: 4px; }
.ep-hero-corpo { font-size: 0.92rem; color: #898781; margin-top: 6px; line-height: 1.5; }
.ep-tagcloud { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: baseline;
              padding: 10px 4px; line-height: 1.9; }
.ep-tag { white-space: nowrap; }
.ep-marca {
    display: inline-flex;
    align-items: center;
    background: #0d0d10;
    border-radius: 10px;
    padding: 6px 16px;
    margin-bottom: 4px;
}
</style>
""", unsafe_allow_html=True)


def render_marca(altura_px: int = 40) -> None:
    """Logo do EsportsPulse (app/assets/pulsesports_logo.png) -- desenhada com
    efeito de brilho (glow branco/laranja) pra superficie ESCURA, que e' o
    fundo padrao do dashboard (ver .streamlit/config.toml): nesse caso o
    fundo escuro da propria pagina ja faz o papel de "chip", entao o logo
    (PNG transparente) e' colocado direto, sem nenhum wrapper. So entra num
    card escuro se alguem trocar manualmente pro tema claro no app -- direto
    em cima do branco, o "P" (branco) quase some por falta de contraste."""
    caminho = ASSETS / "pulsesports_logo.png"
    if not caminho.is_file():
        return
    b64 = base64.b64encode(caminho.read_bytes()).decode()
    img_tag = f'<img src="data:image/png;base64,{b64}" height="{altura_px}" alt="EsportsPulse" />'
    if tema_ativo() == "light":
        st.markdown(f'<div class="ep-marca">{img_tag}</div>', unsafe_allow_html=True)
    else:
        st.markdown(img_tag, unsafe_allow_html=True)


def render_hero(kicker: str, titulo_html: str, corpo_html: str, cor: str) -> None:
    st.markdown(f"""
<div class="ep-hero" style="border-left-color:{cor};">
  <div class="ep-hero-kicker">{kicker}</div>
  <div class="ep-hero-titulo">{titulo_html}</div>
  <div class="ep-hero-corpo">{corpo_html}</div>
</div>
""", unsafe_allow_html=True)


def render_tag_cloud(df: pd.DataFrame, coluna_texto: str = "palavra",
                     coluna_peso: str = "contagem", max_palavras: int = 40) -> None:
    """Nuvem de palavras via HTML/CSS puro -- tamanho de fonte proporcional a
    frequencia. Evita dependencia pesada (wordcloud/Pillow/matplotlib): mais
    leve, mais facil de manter no mesmo pin de versoes do requirements.txt, e
    nativamente tema-aware (usa a cor de texto padrao do Streamlit em vez de
    gerar uma imagem estatica com cor fixa)."""
    if df.empty:
        st.caption("Ainda sem comentários suficientes pra montar a nuvem de palavras.")
        return
    top = df.nlargest(max_palavras, coluna_peso).copy()
    minimo, maximo = top[coluna_peso].min(), top[coluna_peso].max()
    escala = (maximo - minimo) or 1
    # top 3 termos puxam a cor de destaque; o resto usa a cor de texto padrao
    # (identidade so nos que carregam o "achado", nao em toda palavra).
    destaque = set(top.nlargest(3, coluna_peso)[coluna_texto])
    cor_destaque = cor_geral()
    spans = []
    for _, row in top.sample(frac=1, random_state=hash(tuple(top[coluna_texto])) % (2**31)).iterrows():
        peso = (row[coluna_peso] - minimo) / escala
        tam = 0.85 + peso * 1.65   # rem: 0.85 -> 2.5
        cor = cor_destaque if row[coluna_texto] in destaque else "inherit"
        peso_fonte = 700 if row[coluna_texto] in destaque else 400 + int(peso * 300)
        spans.append(
            f'<span class="ep-tag" title="{int(row[coluna_peso])} menções" '
            f'style="font-size:{tam:.2f}rem; font-weight:{peso_fonte}; color:{cor};">'
            f'{row[coluna_texto]}</span>'
        )
    st.markdown(f'<div class="ep-tagcloud">{"".join(spans)}</div>', unsafe_allow_html=True)
