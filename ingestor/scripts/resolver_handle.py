# -*- coding: utf-8 -*-
"""
Resolve um @handle do YouTube para o channel_id (UC...) que o ingestor usa.

O canais.yaml exige o channel_id tecnico (UC...), mas no dia a dia a gente so
conhece o @handle do canal. Este utilitario faz a ponte, gastando 1 unidade de
cota (channels.list) por chamada.

Uso:
  python -m ingestor.scripts.resolver_handle @nomedocanal
  python -m ingestor.scripts.resolver_handle @nomedocanal @outro

Precisa de YOUTUBE_API_KEY no ambiente (copie de .env.example):
  export YOUTUBE_API_KEY=...        # Windows: set YOUTUBE_API_KEY=...
"""
from __future__ import annotations
import os
import sys


def resolver(handle: str, api_key: str) -> dict | None:
    """Retorna {handle, channel_id, nome, uploads_playlist} ou None se nao achar."""
    from googleapiclient.discovery import build

    yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    h = handle if handle.startswith("@") else f"@{handle}"
    resp = yt.channels().list(
        part="id,snippet,contentDetails", forHandle=h).execute()
    items = resp.get("items", [])
    if not items:
        return None
    it = items[0]
    return {
        "handle": h,
        "channel_id": it["id"],
        "nome": it["snippet"]["title"],
        "uploads_playlist": it["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def main(argv: list[str]) -> int:
    handles = [a for a in argv if not a.startswith("-")]
    if not handles:
        print(__doc__)
        return 2

    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("[erro] defina YOUTUBE_API_KEY no ambiente (veja .env.example).")
        return 1

    for handle in handles:
        info = resolver(handle, api_key)
        if not info:
            print(f"[nao encontrado] {handle}")
            continue
        # imprime pronto para colar em config/canais.yaml
        print(f'  # {info["nome"]}  ({info["handle"]})')
        print(f'  channel_id: "{info["channel_id"]}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
