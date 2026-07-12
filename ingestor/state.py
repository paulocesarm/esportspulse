# -*- coding: utf-8 -*-
"""
Estado de ingestao em SQLite — a FONTE DA VERDADE do pipeline.

Responde as tres perguntas do engenheiro de dados:
  1. O que ja ingeri?        -> tabela ingestion_state (PK = video_id)
  2. O que mudou desde a ultima vez? -> watermark por canal (max publishedAt)
  3. Como evito duplicar/corromper?  -> UPSERT idempotente + content_hash

Nada de ORM pesado aqui: SQLite puro, zero setup, didatico.
"""
from __future__ import annotations
import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS ingestion_state (
    video_id        TEXT PRIMARY KEY,
    channel_id      TEXT NOT NULL,
    dominio         TEXT NOT NULL,
    published_at    TEXT,                 -- ISO 8601 (watermark)
    title           TEXT,
    status          TEXT NOT NULL,        -- DISCOVERED|INGESTED|FAILED|SKIPPED
    content_hash    TEXT,                 -- hash da transcricao (detecta mudanca)
    transcript_len  INTEGER DEFAULT 0,
    error           TEXT,
    discovered_at   TEXT NOT NULL,
    ingested_at     TEXT,
    attempts        INTEGER DEFAULT 0,
    -- metricas de audiencia (snapshot no momento da descoberta) + categoria
    -- do YouTube (proxy de "tipo de video") -- usadas pelo Gold pra cruzar
    -- resultado comentado x engajamento.
    view_count      INTEGER DEFAULT 0,
    like_count      INTEGER DEFAULT 0,
    comment_count   INTEGER DEFAULT 0,
    category_id     TEXT
);

CREATE TABLE IF NOT EXISTS channel_watermark (
    channel_id             TEXT PRIMARY KEY,
    last_published_at      TEXT,             -- maior publishedAt ja processado
    last_run_at            TEXT,
    videos_total           INTEGER DEFAULT 0,
    -- Handler de IpBlocked (rate limit do youtube_transcript_api): enquanto
    -- "agora" < blocked_until, o ciclo desse canal e' pulado inteiro (nem
    -- tenta) -- backoff exponencial cresce a cada bloqueio SEGUIDO
    -- (bloqueios_consecutivos), e zera assim que um video ingere com sucesso.
    blocked_until          TEXT,
    bloqueios_consecutivos INTEGER DEFAULT 0
);

-- Estatisticas do CANAL (nao do video) -- inscritos etc, pra analise cross-org.
-- Publico via YouTube Data API (channels.list part=statistics), nao exige
-- OAuth do dono do canal (diferente de audience retention/watch time).
CREATE TABLE IF NOT EXISTS channel_stats (
    channel_id          TEXT PRIMARY KEY,
    dominio             TEXT NOT NULL,
    nome                TEXT,
    subscriber_count    INTEGER DEFAULT 0,
    total_view_count    INTEGER DEFAULT 0,
    video_count         INTEGER DEFAULT 0,
    updated_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_state_channel ON ingestion_state(channel_id);
CREATE INDEX IF NOT EXISTS idx_state_status  ON ingestion_state(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


class StateStore:
    def __init__(self, db_path: str = "./datalake/control/ingestion.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._conn() as c:
            c.executescript(DDL)
            self._migrar_colunas_cooldown(c)

    def _migrar_colunas_cooldown(self, c) -> None:
        # banco criado antes do handler de IpBlocked nao tem essas colunas --
        # CREATE TABLE IF NOT EXISTS nao adiciona coluna em tabela existente.
        for coluna, ddl in (
            ("blocked_until", "ALTER TABLE channel_watermark ADD COLUMN blocked_until TEXT"),
            ("bloqueios_consecutivos",
             "ALTER TABLE channel_watermark ADD COLUMN bloqueios_consecutivos INTEGER DEFAULT 0"),
        ):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass   # coluna ja existe

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- WATERMARK: incrementalidade -------------------------------------
    def get_watermark(self, channel_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT last_published_at FROM channel_watermark WHERE channel_id=?",
                (channel_id,)).fetchone()
            return row["last_published_at"] if row else None

    def update_watermark(self, channel_id: str, published_at: str,
                         novos: int) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT INTO channel_watermark
                    (channel_id, last_published_at, last_run_at, videos_total)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    last_published_at = MAX(excluded.last_published_at,
                                            channel_watermark.last_published_at),
                    last_run_at       = excluded.last_run_at,
                    videos_total      = channel_watermark.videos_total + excluded.videos_total
            """, (channel_id, published_at or "", _now(), novos))

    # --- HANDLER de IpBlocked: cooldown persistido por canal --------------
    def get_cooldown(self, channel_id: str) -> str | None:
        """Timestamp ISO ate quando o canal deve ficar 'de castigo', ou None
        se nao ha cooldown ativo (ou ja passou). Quem chama pula o ciclo
        inteiro desse canal enquanto isso -- nao adianta tentar de novo
        contra um IP que o YouTube ja bloqueou."""
        with self._conn() as c:
            row = c.execute(
                "SELECT blocked_until FROM channel_watermark WHERE channel_id=?",
                (channel_id,)).fetchone()
        if not row or not row["blocked_until"]:
            return None
        return row["blocked_until"] if row["blocked_until"] > _now() else None

    def registrar_bloqueio(self, channel_id: str, cooldown_base_seg: int,
                          cooldown_max_seg: int) -> str:
        """Backoff exponencial: cooldown_base * 2^(bloqueios consecutivos ja
        registrados), com teto em cooldown_max. Cresce a cada bloqueio
        SEGUIDO (sem nenhum sucesso no meio) -- ver limpar_bloqueio."""
        with self._conn() as c:
            row = c.execute(
                "SELECT bloqueios_consecutivos FROM channel_watermark WHERE channel_id=?",
                (channel_id,)).fetchone()
            n = (row["bloqueios_consecutivos"] or 0) if row else 0
            cooldown_seg = min(cooldown_base_seg * (2 ** n), cooldown_max_seg)
            ate = (datetime.now(timezone.utc) + timedelta(seconds=cooldown_seg)).isoformat()
            c.execute("""
                INSERT INTO channel_watermark
                    (channel_id, blocked_until, bloqueios_consecutivos, last_run_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    blocked_until          = excluded.blocked_until,
                    bloqueios_consecutivos = channel_watermark.bloqueios_consecutivos + 1,
                    last_run_at            = excluded.last_run_at
            """, (channel_id, ate, _now()))
        return ate

    def limpar_bloqueio(self, channel_id: str) -> None:
        """Zera o contador assim que um video desse canal ingere com sucesso
        -- o proximo bloqueio (se houver) volta a comecar do cooldown base,
        em vez de continuar crescendo a partir do teto acumulado."""
        with self._conn() as c:
            c.execute("""
                UPDATE channel_watermark
                SET bloqueios_consecutivos = 0, blocked_until = NULL
                WHERE channel_id=?
            """, (channel_id,))

    # --- IDEMPOTENCIA: já processei este video? --------------------------
    def ja_ingerido(self, video_id: str, novo_hash: str | None = None) -> bool:
        """True se o video ja esta INGESTED e o conteudo nao mudou."""
        with self._conn() as c:
            row = c.execute(
                "SELECT status, content_hash FROM ingestion_state WHERE video_id=?",
                (video_id,)).fetchone()
        if not row or row["status"] != "INGESTED":
            return False
        if novo_hash is not None and row["content_hash"] != novo_hash:
            return False   # legenda mudou -> reprocessa
        return True

    def marcar_descoberto(self, video_id, channel_id, dominio,
                          published_at, title, view_count=0, like_count=0,
                          comment_count=0, category_id=None) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT INTO ingestion_state
                    (video_id, channel_id, dominio, published_at, title,
                     status, discovered_at, view_count, like_count,
                     comment_count, category_id)
                VALUES (?, ?, ?, ?, ?, 'DISCOVERED', ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO NOTHING
            """, (video_id, channel_id, dominio, published_at, title, _now(),
                  view_count, like_count, comment_count, category_id))

    def marcar_ingerido(self, video_id, c_hash, t_len) -> None:
        with self._conn() as c:
            c.execute("""
                UPDATE ingestion_state
                SET status='INGESTED', content_hash=?, transcript_len=?,
                    ingested_at=?, attempts=attempts+1, error=NULL
                WHERE video_id=?
            """, (c_hash, t_len, _now(), video_id))

    def marcar_falha(self, video_id, erro) -> None:
        with self._conn() as c:
            c.execute("""
                UPDATE ingestion_state
                SET status='FAILED', error=?, attempts=attempts+1
                WHERE video_id=?
            """, (str(erro)[:300], video_id))

    def videos_falhados(self, channel_id: str) -> list[dict]:
        """Backlog de video FAILED de um canal -- ja conhecemos o video_id,
        entao a re-tentativa nao depende de descobrir() (watermark/API de
        playlist) de novo. Existe pra corrigir um bug real: se algum video
        MAIS NOVO ja tiver sido ingerido com sucesso ANTES da falha (ordem
        de processamento e' sempre do mais novo pro mais antigo), o
        watermark avanca legitimamente ate esse sucesso e qualquer FAILED
        mais antigo que ele fica pra sempre fora do alcance de descobrir()
        -- mesmo a idempotencia normal (retry de FAILED) nunca mais
        acontecendo pra esses videos. Ver ingestor/pipeline.py:rodar_ciclo."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT video_id, channel_id, published_at, title, view_count,
                       like_count, comment_count, category_id
                FROM ingestion_state
                WHERE channel_id=? AND status='FAILED'
                ORDER BY published_at DESC
            """, (channel_id,)).fetchall()
            return [dict(r) for r in rows]

    # --- Metadados p/ cruzar Gold (categoria de conteudo) x audiencia -----
    def metadados_video(self, dominio: str) -> list[dict]:
        """video_id + metricas de audiencia + categoria do YouTube, pra o
        Gold cruzar com a classificacao de conteudo (resultado x engajamento)."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT video_id, channel_id, title, published_at, view_count,
                       like_count, comment_count, category_id
                FROM ingestion_state WHERE dominio=?
            """, (dominio,)).fetchall()
            return [dict(r) for r in rows]

    # --- Estatisticas de canal (analise CROSS entre organizacoes) ---------
    def atualizar_stats_canal(self, channel_id, dominio, nome,
                              subscriber_count, total_view_count,
                              video_count) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT INTO channel_stats
                    (channel_id, dominio, nome, subscriber_count,
                     total_view_count, video_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    nome              = excluded.nome,
                    subscriber_count  = excluded.subscriber_count,
                    total_view_count  = excluded.total_view_count,
                    video_count       = excluded.video_count,
                    updated_at        = excluded.updated_at
            """, (channel_id, dominio, nome, subscriber_count,
                  total_view_count, video_count, _now()))

    def stats_canais(self) -> list[dict]:
        """Estatisticas de todos os canais -- base da analise cross-org."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM channel_stats").fetchall()
            return [dict(r) for r in rows]

    # --- Observabilidade --------------------------------------------------
    def resumo(self) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) n FROM ingestion_state GROUP BY status"
            ).fetchall()
            return {r["status"]: r["n"] for r in rows}
