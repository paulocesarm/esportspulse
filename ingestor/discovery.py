# -*- coding: utf-8 -*-
"""
Descoberta de videos — YouTube Data API v3 com ESTRATEGIA DE COTA.

Cota diaria: 10.000 unidades. Custo por chamada:
  - search.list ............ 100 unidades  (CARO — evitar em loop!)
  - playlistItems.list ......   1 unidade
  - videos.list .............   1 unidade
  - channels.list ...........   1 unidade

Estrategia correta (decisao de ENGENHARIA):
  1. channels.list UMA vez -> pega a playlist de uploads do canal (UU...).
  2. playlistItems.list a cada ciclo (1 unidade) -> lista uploads recentes.
  3. videos.list em lote de ate 50 IDs (1 unidade) -> metadados ricos.
Assim um canal custa ~2 unidades/ciclo em vez de 100+. Da pra rodar
dezenas de canais o dia inteiro dentro da cota gratuita.

Em modo_demo=True, nada disso e chamado: geramos metadados sinteticos
deterministicos para a aula rodar sem API key e sem gastar cota.
"""
from __future__ import annotations
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

from .utils import duracao_iso_para_segundos


@dataclass
class VideoMeta:
    video_id: str
    channel_id: str
    title: str
    description: str
    published_at: str          # ISO 8601 — usado como watermark
    duration_iso: str          # PT#M#S
    view_count: int
    like_count: int
    comment_count: int
    tags: list
    category_id: str
    default_audio_language: str

    def to_row(self) -> dict:
        d = asdict(self)
        d["tags"] = ",".join(self.tags)   # achata p/ parquet/sqlite
        return d


# ---------------------------------------------------------------------------
# Implementacao REAL (Data API v3)
# ---------------------------------------------------------------------------
class YouTubeDiscovery:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self._yt = None

    def _client(self):
        if self._yt is None:
            from googleapiclient.discovery import build
            self._yt = build("youtube", "v3", developerKey=self.api_key,
                             cache_discovery=False)
        return self._yt

    def _uploads_playlist(self, channel_id: str) -> str:
        resp = self._client().channels().list(
            part="contentDetails", id=channel_id).execute()
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Canal nao encontrado: {channel_id}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # trava de seguranca: no maximo N paginas de 50 (~500 candidatos) por
    # chamada, mesmo que duracao_min_seg exija cavar fundo num canal cheio
    # de shorts. Evita loop caro/infinito em canais com historico enorme.
    _LIMITE_PAGINAS = 10

    def descobrir(self, channel_id: str, since_iso: str | None,
                  max_videos: int, janela_dias: int,
                  duracao_min_seg: int = 0) -> list[VideoMeta]:
        uploads = self._uploads_playlist(channel_id)
        corte = (datetime.now(timezone.utc) - timedelta(days=janela_dias)).isoformat()

        out: list[VideoMeta] = []
        page = None
        for _ in range(self._LIMITE_PAGINAS):
            resp = self._client().playlistItems().list(
                part="contentDetails", playlistId=uploads,
                maxResults=50, pageToken=page).execute()
            ids_pagina = [it["contentDetails"]["videoId"]
                         for it in resp.get("items", [])]

            # NAO filtra por contentDetails.videoPublishedAt (instavel na API);
            # hidrata e usa snippet.publishedAt, que e confiavel.
            hidratados = self._hidratar(channel_id, ids_pagina)
            hidratados.sort(key=lambda v: v.published_at, reverse=True)

            parou = False
            for v in hidratados:
                if since_iso and v.published_at <= since_iso:
                    parou = True   # passou do watermark, o resto e mais velho ainda
                    break
                if v.published_at < corte:
                    continue
                if duracao_min_seg and duracao_iso_para_segundos(v.duration_iso) < duracao_min_seg:
                    continue       # short/clip — nao conta como candidato valido
                out.append(v)
                if len(out) >= max_videos:
                    parou = True
                    break

            page = resp.get("nextPageToken")
            if parou or not page:
                break
        return out

    def _hidratar(self, channel_id: str, ids: list[str]) -> list[VideoMeta]:
        if not ids:
            return []
        resp = self._client().videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(ids), maxResults=50).execute()
        out = []
        for it in resp.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            cd = it.get("contentDetails", {})
            out.append(VideoMeta(
                video_id=it["id"], channel_id=channel_id,
                title=sn.get("title", ""), description=sn.get("description", "")[:500],
                published_at=sn.get("publishedAt", ""),
                duration_iso=cd.get("duration", ""),
                view_count=int(st.get("viewCount", 0)),
                like_count=int(st.get("likeCount", 0)),
                comment_count=int(st.get("commentCount", 0)),
                tags=sn.get("tags", []), category_id=sn.get("categoryId", ""),
                default_audio_language=sn.get("defaultAudioLanguage", ""),
            ))
        return out


# ---------------------------------------------------------------------------
# Implementacao DEMO (sintetica, deterministica) — mesma interface
# ---------------------------------------------------------------------------
class DemoDiscovery:
    """Substitui a API real. Gera videos 'novos' a cada ciclo de forma
    deterministica por canal+dia, para demonstrar watermark/incrementalidade."""
    def descobrir(self, channel_id: str, since_iso: str | None,
                  max_videos: int, janela_dias: int,
                  duracao_min_seg: int = 0) -> list[VideoMeta]:
        rng = random.Random(f"{channel_id}-{datetime.now().strftime('%Y%m%d%H')}")
        n = rng.randint(1, max_videos)
        agora = datetime.now(timezone.utc)
        out = []
        for i in range(n):
            pub = (agora - timedelta(hours=rng.randint(0, 24 * janela_dias)))
            pub_iso = pub.isoformat()
            if since_iso and pub_iso <= since_iso:
                continue  # respeita o watermark, como a API real faria
            vid = f"demo_{channel_id[-4:]}_{pub.strftime('%j%H')}_{i}"
            out.append(VideoMeta(
                video_id=vid, channel_id=channel_id,
                title=f"Video {i} do canal {channel_id[-4:]}",
                description="conteudo sintetico para a aula",
                published_at=pub_iso, duration_iso=f"PT{rng.randint(3,40)}M",
                view_count=rng.randint(1_000, 500_000),
                like_count=rng.randint(50, 30_000),
                comment_count=rng.randint(0, 5_000),
                tags=["demo", "aula", "eng-dados"],
                category_id="27", default_audio_language="pt",
            ))
        return out


def get_discovery(modo_demo: bool):
    return DemoDiscovery() if modo_demo else YouTubeDiscovery()
