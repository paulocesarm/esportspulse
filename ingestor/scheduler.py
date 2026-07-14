# -*- coding: utf-8 -*-
"""
Entrypoint da ingestao perene. Usa APScheduler para agendar CADA canal no
seu proprio intervalo (decisao de negocio definida em config/canais.yaml).

Uso:
  python -m ingestor.scheduler            # roda perene (Ctrl+C para sair)
  python -m ingestor.scheduler --once     # roda 1 ciclo de cada canal e sai
  python -m ingestor.scheduler --status   # imprime resumo do estado

Para rodar como servico na VPS, ver deploy/ingestor.service (systemd).
"""
from __future__ import annotations
import sys
import time
import logging
from pathlib import Path

import yaml
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .state import StateStore
from .pipeline import rodar_ciclo

# Carrega .env (YOUTUBE_API_KEY) quando rodado localmente. Na VPS, o
# deploy/ingestor.service ja injeta via EnvironmentFile=.env (systemd).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("scheduler")

CONFIG = Path(__file__).resolve().parent.parent / "config" / "canais.yaml"


def carregar_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Pausa entre CANAIS (nao so entre videos do mesmo canal, ja tratado em
# pipeline.py) no --once: sem isso, o ultimo video de um canal e o primeiro
# do proximo saem colados, e os 5 canais juntos viram uma rajada continua
# contra o mesmo IP -- justamente o cenario que leva a IpBlocked.
_PAUSA_ENTRE_CANAIS_SEG = 30


def rodar_uma_vez(cfg: dict, store: StateStore):
    glob = cfg.get("global", {})
    modo_demo = glob.get("modo_demo", True)
    primeiro = True
    for canal in cfg["canais"]:
        if not canal.get("ativo", True):
            continue
        if not primeiro and not modo_demo:
            log.info("pausa de %ds antes do proximo canal", _PAUSA_ENTRE_CANAIS_SEG)
            time.sleep(_PAUSA_ENTRE_CANAIS_SEG)
        primeiro = False
        rodar_ciclo(canal, glob, store)


def main():
    cfg = carregar_config()
    store = StateStore()

    if "--status" in sys.argv:
        print("Estado de ingestao:", store.resumo())
        return
    if "--once" in sys.argv:
        log.info("Execucao unica (--once)")
        rodar_uma_vez(cfg, store)
        print("Resumo final:", store.resumo())
        return

    sched = BlockingScheduler(timezone="America/Fortaleza")
    glob = cfg.get("global", {})
    for canal in cfg["canais"]:
        if not canal.get("ativo", True):
            continue
        intervalo = canal.get("intervalo_min", 60)
        sched.add_job(
            rodar_ciclo, IntervalTrigger(minutes=intervalo),
            args=[canal, glob, store],
            id=canal["channel_id"], name=canal["nome"],
            max_instances=1, coalesce=True)    # nao acumula execucoes atrasadas
        log.info("agendado: %s a cada %d min", canal["nome"], intervalo)

    log.info("Ingestor perene iniciado. Ctrl+C para encerrar.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("encerrando...")


if __name__ == "__main__":
    main()
