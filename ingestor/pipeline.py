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
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import polars as pl
import yaml
import pandera.pandas as pa
from pandera.pandas import Column, DataFrameSchema, Check

from youtube_transcript_api._errors import RequestBlocked

from .state import StateStore, content_hash
from .discovery import get_discovery, VideoMeta
from .transcript import extrair_transcricao
from .utils import duracao_iso_para_segundos as _duracao_segundos, slug_organizacao

log = logging.getLogger("ingestor")

STOPWORDS = {
    "entao", "olha", "ne", "tipo", "veja", "bem", "o", "a", "que", "de", "e",
    "aqui", "isso", "na", "pratica",
    # ampliado pra limpar tambem comentario de publico (mais informal e
    # variado que a transcricao) -- sem isso, a nuvem de palavras fica
    # dominada por preenchimento generico (nao, pra, com, uma...) em vez de
    # termo com sinal (nome de jogador, time, jogo).
    "nao", "pra", "para", "por", "com", "sem", "sob", "sao", "ser", "tem",
    "mas", "uma", "um", "os", "as", "no", "em", "ate", "mais", "muito",
    "esse", "essa", "esses", "essas", "este", "esta", "estes", "estas",
    "isso", "aquele", "aquela", "outro", "outra", "outros", "outras",
    "meu", "minha", "seu", "sua", "dele", "dela", "deles", "delas",
    "nos", "voce", "voces", "ele", "ela", "eles", "elas", "eu", "tu",
    "vou", "vai", "vamos", "foi", "sera", "seria", "pode", "podem",
    "quando", "onde", "como", "porque", "pois", "todo", "toda", "todos",
    "todas", "cara", "coisa", "the", "and", "for", "you", "que", "dos",
    "das", "pelo", "pela", "num", "numa", "la", "ali", "ja", "so",
}

# Mesmo contrato Silver dos 10 notebooks (Desafio 1), incluindo n_palavras.
# texto_deteccao: como texto_limpo, mas SEM remover digito e SEM stopword/
# filtro de tamanho -- usado so pela deteccao de modalidade (_detectar_jogo),
# que precisa achar "cs2"/"r6" (o regex de texto_limpo removia o digito e
# nunca batia com o vocabulario de config/sinais.yaml).
SILVER_SCHEMA = DataFrameSchema({
    "video_id":       Column(str, nullable=False),
    "ordem":          Column(int, Check.ge(0)),
    "texto_limpo":    Column(str, Check.str_length(min_value=1)),
    "texto_deteccao": Column(str, Check.str_length(min_value=1)),
    "start":          Column(float, Check.ge(0)),
    "duration":       Column(float, Check.gt(0)),
    "n_palavras":     Column(int, Check.ge(1)),
}, coerce=True)

_SINAIS_PATH = Path(__file__).resolve().parent.parent / "config" / "sinais.yaml"


def _carregar_sinais() -> tuple[list[str], list[str], list[str]]:
    """Sinais compartilhados entre canais (config/sinais.yaml): contexto de
    jogo (o video sequer fala de partida/torneio?) + resultado positivo/
    negativo (so faz sentido classificar DENTRO de video que ja tem contexto
    de jogo — ver comentario do sinais.yaml sobre falso positivo em video de
    entretenimento generico)."""
    if not _SINAIS_PATH.is_file():
        return [], [], []
    dados = yaml.safe_load(_SINAIS_PATH.read_text(encoding="utf-8")) or {}
    return (dados.get("contexto_jogo", []),
            dados.get("resultado_positivo", []),
            dados.get("resultado_negativo", []))


def _carregar_jogos() -> dict[str, list[str]]:
    """Frases que identificam cada JOGO dentro da transcricao. Detectado por
    VIDEO, nao por canal: uma organizacao (FURIA, MIBR...) tem varias
    modalidades (CS2, Valorant, LoL...) no mesmo canal institucional."""
    if not _SINAIS_PATH.is_file():
        return {}
    dados = yaml.safe_load(_SINAIS_PATH.read_text(encoding="utf-8")) or {}
    return dados.get("jogos", {})


def _carregar_elencos() -> dict[str, dict[str, list[str]]]:
    """Nomes de jogador por canal+jogo (config/sinais.yaml: elencos) -- sinal
    ADICIONAL de deteccao de modalidade, somado aos termos de 'jogos' pra
    video que cita jogador sem falar o nome do jogo explicitamente."""
    if not _SINAIS_PATH.is_file():
        return {}
    dados = yaml.safe_load(_SINAIS_PATH.read_text(encoding="utf-8")) or {}
    return dados.get("elencos", {})


def _detectar_jogo(texto_completo: str, jogos: dict[str, list[str]],
                   elenco_canal: dict[str, list[str]] | None = None) -> str:
    """Conta ocorrencia de frase por jogo no texto completo do video (nao
    token a token, porque tem frase composta tipo 'league of legends'), somando
    tambem os nomes de jogador do elenco daquele canal especifico (ver
    _carregar_elencos) a contagem do jogo correspondente."""
    fontes = {jogo: list(termos) for jogo, termos in jogos.items()}
    for jogo, nomes in (elenco_canal or {}).items():
        fontes.setdefault(jogo, []).extend(nomes)
    contagem = {jogo: sum(texto_completo.count(termo) for termo in termos)
               for jogo, termos in fontes.items()}
    if not contagem or max(contagem.values(), default=0) == 0:
        return "indefinido"
    return max(contagem, key=contagem.get)


def _remover_acentos(texto: str) -> str:
    """NFKD decompoe 'á'->'a'+acento; filtra as marcas combinantes."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _limpar(texto: str) -> str:
    # BUG antigo: o regex so deixava passar [a-z] puro, entao "vitória"
    # virava "vit ria" (o "ó" virava espaco) -- nunca batia com "vitoria" no
    # sinais.yaml. Remove acento ANTES de filtrar caracteres.
    texto = _remover_acentos(texto.lower())
    texto = re.sub(r"[^a-z\s]", " ", texto)
    return " ".join(t for t in texto.split()
                    if t not in STOPWORDS and len(t) > 2)


def _normalizar_deteccao(texto: str) -> str:
    # BUG real (achado com dado da FURIA, canal 100% CS2): _limpar() acima
    # remove digito (regex so deixa [a-z]), entao "CS2" virava "cs" e "R6"
    # virava "r" -- nunca batiam com "cs2"/"r6" em config/sinais.yaml. Aqui o
    # regex mantem [a-z0-9], e nao filtra stopword/tamanho (precisa preservar
    # token curto como "r6"/"kye" e frase composta como "counter strike").
    texto = _remover_acentos(texto.lower())
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return " ".join(texto.split())


_QUARENTENA_DIR = Path("./datalake/silver/_quarentena")


def _persistir_bronze(trechos: list[dict], dominio: str, organizacao: str, video_id: str) -> None:
    """Grava a transcricao crua (Bronze), antes de qualquer limpeza/validacao."""
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = Path(f"./datalake/bronze/dominio={dominio}/organizacao={organizacao}/dt={dia}")
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
    df["texto_deteccao"] = df["texto"].apply(_normalizar_deteccao)
    df = df[df["texto_limpo"].str.len() > 0].copy()
    df["n_palavras"] = df["texto_limpo"].str.split().str.len().fillna(0).astype(int)
    bruto = df[["video_id", "ordem", "texto_limpo", "texto_deteccao",
               "start", "duration", "n_palavras"]]
    try:
        return SILVER_SCHEMA.validate(bruto)
    except pa.errors.SchemaError:
        _persistir_quarentena(bruto, video_id)
        raise


def _persistir(df: pd.DataFrame, dominio: str, organizacao: str, video_id: str):
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = Path(f"./datalake/silver/dominio={dominio}/organizacao={organizacao}/dt={dia}")
    base.mkdir(parents=True, exist_ok=True)
    df.to_parquet(base / f"{video_id}.parquet", index=False)


# --------------------------------------------------------------------------- #
# Comentarios — texto real (nao so contagem), base da nuvem de palavras do
# dashboard. Mesmo padrao bronze/silver/gold da transcricao, mas em sub-pasta
# "comentarios" pra nao misturar com os trechos de transcricao.
# --------------------------------------------------------------------------- #
def _persistir_bronze_comentarios(comentarios: list[dict], dominio: str, organizacao: str,
                                  channel_id: str, video_id: str) -> None:
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = Path(f"./datalake/bronze/dominio={dominio}/organizacao={organizacao}/comentarios/dt={dia}")
    base.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([{**c, "channel_id": channel_id, "video_id": video_id}
                       for c in comentarios])
    df.to_parquet(base / f"{video_id}.parquet", index=False)


def _bronze_silver_comentarios(video_id: str, channel_id: str,
                               comentarios: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(comentarios)
    df["texto_limpo"] = df["texto"].apply(_limpar)
    df = df[df["texto_limpo"].str.len() > 0].copy()
    df["video_id"] = video_id
    df["channel_id"] = channel_id
    return df[["video_id", "channel_id", "comentario_id", "texto_limpo", "like_count"]]


def _persistir_comentarios(df: pd.DataFrame, dominio: str, organizacao: str, video_id: str) -> None:
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = Path(f"./datalake/silver/dominio={dominio}/organizacao={organizacao}/comentarios/dt={dia}")
    base.mkdir(parents=True, exist_ok=True)
    df.to_parquet(base / f"{video_id}.parquet", index=False)


def _gold_palavras(dominio: str) -> pd.DataFrame:
    """Frequencia de palavra por canal, a partir do texto real dos
    comentarios -- alimenta a nuvem de palavras do dashboard (Geral: soma
    todos os canais; Por Time: filtra por channel_id)."""
    src = f"./datalake/silver/dominio={dominio}/organizacao=*/comentarios/**/*.parquet"
    try:
        df = pl.scan_parquet(src).select(["channel_id", "texto_limpo"]).collect().to_pandas()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    tokens = df.assign(palavra=df["texto_limpo"].str.split(" ")).explode("palavra")
    tokens = tokens[tokens["palavra"].str.len() > 0]
    freq = (tokens.groupby(["channel_id", "palavra"]).size()
                  .rename("contagem").reset_index()
                  .sort_values("contagem", ascending=False))
    out = Path(f"./datalake/gold/dominio={dominio}")
    out.mkdir(parents=True, exist_ok=True)
    freq.to_parquet(out / "palavras_comentarios.parquet", index=False)
    return freq


def _gold(dominio: str, sinais_jogo: list[str], sinais_pos: list[str],
          sinais_neg: list[str], jogos: dict[str, list[str]],
          elencos: dict[str, dict[str, list[str]]],
          store: StateStore) -> pd.DataFrame:
    """Classifica cada VIDEO em tres eixos e cruza com audiencia real:

    1. tipo: 'jogo' (fala de partida/torneio/adversario) ou 'entretenimento'
       (vlog/desafio generico sem relacao com o jogo).
    2. Dentro de tipo='jogo': categoria = resultado_positivo/negativo/
       indefinido (resultado comentado ou nao).
    3. jogo_detectado: qual MODALIDADE (cs2/valorant/lol/freefire/r6/
       indefinido) o video menciona — por video, nao por canal, porque uma
       organizacao tem varias modalidades no mesmo canal institucional.

    Por que dois niveis (tipo->categoria): os canais reais monitorados tem
    tipos de conteudo MUITO diferentes (vlog de torneio real, comentario/
    analise de gameplay, entretenimento generico sem nada a ver com o jogo).
    Aplicar resultado_positivo/negativo direto no video inteiro gera falso
    positivo grave (ex.: "voce perdeu" numa brincadeira dentro de um vlog de
    casa assombrada, sem nenhuma relacao com o resultado da partida real).

    Cruza com view_count/like_count/comment_count/category_id (por video,
    do SQLite) -- usados na analise INTRA-canal (tipo de conteudo x
    engajamento). channel_id tambem vai junto, pra viabilizar a analise
    CROSS-org e a visao geral do mercado (ver state.stats_canais).
    """
    # organizacao=*/dt=*/*.parquet (nao "**"): "**" tambem cairia dentro de
    # organizacao=X/comentarios/dt=.../ (schema diferente -- comentario, nao
    # trecho de transcricao), quebrando o scan_parquet e derrubando o Gold
    # inteiro em silencio (capturado pelo except abaixo).
    src = f"./datalake/silver/dominio={dominio}/organizacao=*/dt=*/*.parquet"
    jogo_set, pos, neg = set(sinais_jogo), set(sinais_pos), set(sinais_neg)
    try:
        trechos = pl.scan_parquet(src).select(
            ["video_id", "texto_limpo", "texto_deteccao"]).collect()
        por_video = (
            trechos.lazy()
            .with_columns(pl.col("texto_limpo").str.split(" ").alias("tokens"))
            .with_columns([
                pl.col("tokens").list.eval(pl.element().is_in(list(jogo_set))).list.sum().alias("hits_jogo"),
                pl.col("tokens").list.eval(pl.element().is_in(list(pos))).list.sum().alias("hits_pos"),
                pl.col("tokens").list.eval(pl.element().is_in(list(neg))).list.sum().alias("hits_neg"),
            ])
            .group_by("video_id")
            .agg([
                pl.col("hits_jogo").sum().alias("hits_jogo"),
                pl.col("hits_pos").sum().alias("hits_pos"),
                pl.col("hits_neg").sum().alias("hits_neg"),
                pl.len().alias("trechos_total"),
            ])
            .with_columns(
                pl.when(pl.col("hits_jogo") > 0).then(pl.lit("jogo"))
                  .otherwise(pl.lit("entretenimento")).alias("tipo")
            )
            .with_columns(
                pl.when(pl.col("tipo") != "jogo").then(pl.lit(None))
                  .when(pl.col("hits_pos") > pl.col("hits_neg")).then(pl.lit("resultado_positivo"))
                  .when(pl.col("hits_neg") > pl.col("hits_pos")).then(pl.lit("resultado_negativo"))
                  .otherwise(pl.lit("indefinido")).alias("categoria")
            )
            .collect()
            .to_pandas()
        )
    except Exception:
        return pd.DataFrame()   # ainda sem dados silver pra esse dominio

    # metricas (channel_id inclusive) buscadas ANTES da deteccao de jogo pra
    # poder somar o elenco (nomes de jogador) especifico do canal daquele
    # video -- ver config/sinais.yaml:elencos e _detectar_jogo.
    metricas = pd.DataFrame(store.metadados_video(dominio))
    vid_para_canal = (dict(zip(metricas["video_id"], metricas["channel_id"]))
                      if not metricas.empty else {})

    # deteccao de jogo: frase composta ("league of legends"), nao token a
    # token -- feita em pandas sobre o texto completo (todos os trechos
    # concatenados) de cada video. Usa texto_deteccao (preserva digito:
    # "cs2"/"r6"), nao texto_limpo (ver _normalizar_deteccao).
    texto_por_video = (trechos.to_pandas().groupby("video_id")["texto_deteccao"]
                      .apply(lambda s: " " + " ".join(s) + " "))
    por_video["jogo_detectado"] = por_video["video_id"].map(
        lambda vid: _detectar_jogo(texto_por_video.get(vid, ""), jogos,
                                   elencos.get(vid_para_canal.get(vid), {})))

    if metricas.empty:
        gold = por_video
        for col in ("channel_id", "view_count", "like_count", "comment_count",
                   "category_id", "title"):
            gold[col] = None
    else:
        gold = por_video.merge(metricas, on="video_id", how="left")

    out = Path(f"./datalake/gold/dominio={dominio}")
    out.mkdir(parents=True, exist_ok=True)
    gold.to_parquet(out / "resultado_engajamento.parquet", index=False)
    return gold


def _video_do_backlog(row: dict) -> VideoMeta:
    """Reconstroi um VideoMeta a partir de uma linha FAILED do SQLite (ver
    StateStore.videos_falhados) -- ja temos video_id/metricas, nao precisa
    redescobrir via API. Campos so usados no momento da descoberta
    (duracao/tags/idioma) ficam vazios -- sem uso no re-processamento."""
    return VideoMeta(
        video_id=row["video_id"], channel_id=row["channel_id"],
        title=row["title"] or "", description="",
        published_at=row["published_at"] or "", duration_iso="",
        view_count=row["view_count"] or 0, like_count=row["like_count"] or 0,
        comment_count=row["comment_count"] or 0, tags=[],
        category_id=row["category_id"] or "", default_audio_language="",
    )


# Resultado de _processar_video: o que aconteceu com ESSE video.
_INGERIDO, _PULADO_IDEMPOTENTE, _FALHA = "ingerido", "pulado", "falha"


def _processar_video(v: VideoMeta, cid: str, dom: str, organizacao: str, vocab: list[str],
                     modo_demo: bool, glob_cfg: dict, store: StateStore,
                     disc) -> str:
    """Capta transcricao + persiste Bronze/Silver + comentarios de UM video.
    Levanta RequestBlocked (nao captura) -- quem chama decide abortar o
    ciclo e registrar o cooldown. Usado tanto pro backlog de FAILED quanto
    pra descoberta nova (mesma logica, sem duplicar)."""
    store.marcar_descoberto(v.video_id, cid, dom, v.published_at, v.title,
                            v.view_count, v.like_count, v.comment_count,
                            v.category_id)

    trechos = extrair_transcricao(
        v.video_id, glob_cfg.get("idiomas_legenda", ["pt", "en"]),
        vocab, modo_demo, glob_cfg.get("transcript_retry_backoff_seg", 20))
    if not trechos:
        store.marcar_falha(v.video_id, "sem legenda")
        return _FALHA

    texto_total = " ".join(t["text"] for t in trechos)
    h = content_hash(texto_total)
    if store.ja_ingerido(v.video_id, h):   # IDEMPOTENCIA
        return _PULADO_IDEMPOTENTE

    try:
        _persistir_bronze(trechos, dom, organizacao, v.video_id)   # captura crua, sempre
        df = _bronze_silver(v.video_id, trechos)
        _persistir(df, dom, organizacao, v.video_id)
        store.marcar_ingerido(v.video_id, h, len(df))
        store.limpar_bloqueio(cid)   # sucesso -- zera o contador de bloqueio seguido
    except (pa.errors.SchemaError, Exception) as e:
        store.marcar_falha(v.video_id, e)
        return _FALHA

    # comentarios reais (nuvem de palavras) -- best-effort: video ja esta
    # INGESTED pela transcricao, entao falha aqui nunca deve derrubar o
    # ciclo nem desfazer o que ja foi persistido.
    try:
        comentarios = disc.comentarios_video(v.video_id)
        if comentarios:
            _persistir_bronze_comentarios(comentarios, dom, organizacao, cid, v.video_id)
            dfc = _bronze_silver_comentarios(v.video_id, cid, comentarios)
            if not dfc.empty:
                _persistir_comentarios(dfc, dom, organizacao, v.video_id)
    except Exception as e:
        log.warning("falha ao buscar comentarios de %s: %s", v.video_id, e)

    return _INGERIDO


def rodar_ciclo(canal: dict, glob_cfg: dict, store: StateStore) -> dict:
    """Executa um ciclo completo de ingestao para um canal. Idempotente."""
    cid, dom = canal["channel_id"], canal["dominio"]
    # particao aninhada dominio=X/organizacao=Y -- pasta legivel por time
    # dentro do dominio compartilhado (ver comentario em config/canais.yaml).
    organizacao = slug_organizacao(canal["nome"])

    # Handler de IpBlocked: canal em cooldown (bloqueado numa tentativa
    # recente) e' pulado INTEIRO -- nem tenta de novo contra um IP que o
    # YouTube ja bloqueou (ver StateStore.get_cooldown/registrar_bloqueio).
    cooldown_ate = store.get_cooldown(cid)
    if cooldown_ate:
        log.info("%s em cooldown ate %s -- pulando o ciclo", canal["nome"], cooldown_ate)
        return {"canal": canal["nome"], "descobertos": 0, "ingeridos": 0,
               "pulados_idempotencia": 0, "falhas": 0, "descartados_duracao": 0,
               "em_cooldown_ate": cooldown_ate}

    sinais_jogo, sinais_pos, sinais_neg = _carregar_sinais()
    jogos = _carregar_jogos()
    elencos = _carregar_elencos()
    # sem 'vocabulario' proprio no canal -> usa os sinais compartilhados
    vocab = canal.get("vocabulario", []) or (sinais_jogo + sinais_pos + sinais_neg)
    disc = get_discovery(glob_cfg.get("modo_demo", True))

    # estatisticas do canal (inscritos etc) -- base da analise cross-org
    stats = disc.estatisticas_canal(cid)
    store.atualizar_stats_canal(cid, dom, stats["nome"], stats["subscriber_count"],
                                stats["total_view_count"], stats["video_count"])

    duracao_min = canal.get("duracao_min_seg", 0)
    modo_demo = glob_cfg.get("modo_demo", True)
    # Pausa entre chamadas de transcricao (youtube_transcript_api), em
    # segundos -- evita rajada de requisicoes que leva a IpBlocked.
    delay = 2

    novos, ingeridos, pulados, falhas = 0, 0, 0, 0
    recuperados_backlog = 0
    bloqueado = False

    def _bloquear(video_id: str, erro) -> None:
        nonlocal bloqueado
        store.marcar_falha(video_id, f"IP bloqueado: {erro}")
        ate = store.registrar_bloqueio(
            cid, glob_cfg.get("transcript_cooldown_base_seg", 900),
            glob_cfg.get("transcript_cooldown_max_seg", 7200))
        log.warning("IP bloqueado durante %s -- abortando o ciclo e "
                   "pulando esse canal ate %s", canal["nome"], ate)
        bloqueado = True

    # --- FASE 1: backlog de FAILED (nao depende de watermark/descoberta) ---
    # Corrige um bug real: se um video MAIS NOVO ja ingeriu com sucesso antes
    # de bater numa falha (ordem sempre do mais novo pro mais antigo), o
    # watermark avanca legitimamente ate esse sucesso e qualquer FAILED mais
    # antigo que ele nunca mais aparece via descobrir() -- fica preso pra
    # sempre, mesmo a idempotencia normal (retry de FAILED) nunca disparando
    # de novo pra esse video. Ver StateStore.videos_falhados.
    backlog = [_video_do_backlog(r) for r in store.videos_falhados(cid)]
    for i, v in enumerate(backlog):
        if i > 0 and not modo_demo and delay:
            time.sleep(delay)
        try:
            status = _processar_video(v, cid, dom, organizacao, vocab, modo_demo, glob_cfg, store, disc)
        except RequestBlocked as e:
            _bloquear(v.video_id, e)
            break
        if status == _INGERIDO:
            ingeridos += 1
            recuperados_backlog += 1
        elif status == _PULADO_IDEMPOTENTE:
            pulados += 1
        else:
            falhas += 1

    # --- FASE 2: descoberta nova (via watermark, como antes) ---------------
    descartados_duracao = 0
    if not bloqueado:
        watermark = store.get_watermark(cid)
        # sempre exatamente o que esta em canais.yaml -- mesmo teto e mesma
        # janela em todo ciclo (inicial ou incremental), sem escalonamento.
        videos = disc.descobrir(cid, watermark,
                                canal.get("max_videos_por_ciclo", 5),
                                glob_cfg.get("janela_descoberta_dias", 30),
                                duracao_min)

        # backstop: a DemoDiscovery nao filtra por duracao sozinha (a real ja filtra)
        if duracao_min:
            antes = len(videos)
            videos = [v for v in videos if _duracao_segundos(v.duration_iso) >= duracao_min]
            descartados_duracao = antes - len(videos)

        max_pub = watermark or ""
        # 'videos' vem ordenado do mais novo pro mais antigo (ver discovery.py).
        # O watermark so pode avancar atraves de uma sequencia CONTINUA de
        # sucesso a partir do mais novo -- na primeira falha, paramos de
        # avancar. (O backlog da FASE 1 acima e' quem garante que uma falha
        # aqui nao fique presa pra sempre, independente desse avanco.)
        pode_avancar_watermark = True
        for i, v in enumerate(videos):
            if i > 0 and not modo_demo and delay:
                time.sleep(delay)
            novos += 1
            try:
                status = _processar_video(v, cid, dom, organizacao, vocab, modo_demo, glob_cfg, store, disc)
            except RequestBlocked as e:
                _bloquear(v.video_id, e)
                falhas += 1
                pode_avancar_watermark = False
                break
            if status == _INGERIDO:
                ingeridos += 1
                if pode_avancar_watermark:
                    max_pub = max(max_pub, v.published_at or "")
            elif status == _PULADO_IDEMPOTENTE:
                pulados += 1
                if pode_avancar_watermark:
                    max_pub = max(max_pub, v.published_at or "")
            else:
                falhas += 1
                pode_avancar_watermark = False

        if novos:
            store.update_watermark(cid, max_pub, ingeridos)

    _gold(dom, sinais_jogo, sinais_pos, sinais_neg, jogos, elencos, store)
    _gold_palavras(dom)

    res = {"canal": canal["nome"], "descobertos": novos, "ingeridos": ingeridos,
           "pulados_idempotencia": pulados, "falhas": falhas,
           "descartados_duracao": descartados_duracao,
           "recuperados_do_backlog": recuperados_backlog}
    log.info("ciclo %s -> %s", canal["nome"], res)
    return res
