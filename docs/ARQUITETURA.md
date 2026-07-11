# Arquitetura

> Template da §7.2. Diagrama do fluxo + decisões técnicas.

## Visão geral

Lakehouse em camadas (padrão da disciplina, evoluído do `projeto_modelo/`):

```
canais.yaml ──► ingestor.scheduler (--once | perene | --status)
                       │
                       ▼
               rodar_ciclo(canal)
                       │
     descobrir (incremental via watermark, YouTube Data API v3)
        └─ playlistItems.list ..... paginado, cava fundo ate achar
                                    video que passe no filtro de duracao
        └─ videos.list ............ hidrata metadados confiaveis
                       │
     para cada vídeo NOVO e NÃO-ingerido (idempotência = video_id + content_hash):
         captar transcrição ............ BRONZE  → parquet dominio=/dt=
         limpar + contrato Pandera ..... SILVER  → parquet dominio=/dt=
           (falha de contrato ......... _quarentena, sem travar o ciclo)
         atualizar estado SQLite ....... watermark + idempotência
     rodar analítico do domínio ....... GOLD    → resultado comentado (vitória/derrota/
                                                   sem menção) por vídeo, cruzado com
                                                   audiência real (views/likes/comments)
     avançar o watermark do canal

Apresentação: dashboard Streamlit lê o GOLD (Parquet) + controle (SQLite)
Produção:     systemd (ingestor.service + streamlit.service) na VPS
```

## Camadas

| Camada | O que faz neste projeto | Onde |
|---|---|---|
| **Bronze** | Captura bruta da transcrição (`youtube_transcript_api`), gravada como veio, antes de qualquer limpeza | `ingestor/pipeline.py` (`_persistir_bronze`) |
| **Silver** | Limpeza de texto + contrato Pandera (`video_id`, `ordem`, `texto_limpo`, `start`, `duration`, `n_palavras`) + quarentena de descartes | `ingestor/pipeline.py` (`_bronze_silver`, `_persistir_quarentena`) |
| **Gold** | Classifica cada vídeo pelo resultado comentado (`resultado_positivo`/`resultado_negativo`/`sem_resultado`, via `config/sinais.yaml`) e cruza com métricas de audiência (`view_count`, `like_count`, `comment_count`, `category_id`) do SQLite | `ingestor/pipeline.py` (`_gold`) |
| **Controle** | Watermark por canal + idempotência por `video_id`/`content_hash` + snapshot de métricas de audiência na descoberta | `ingestor/state.py` (SQLite, `datalake/control/ingestion.db`) |
| **Agendamento** | Ingestão perene por canal via `APScheduler`, um intervalo por canal | `ingestor/scheduler.py` + `config/canais.yaml` |
| **Apresentação** | Dashboard Streamlit lendo Gold (Parquet) + metadados de confiabilidade do SQLite | `app/streamlit_app.py` |

## Decisões técnicas

- **Por que Parquet particionado por `dominio=`/`dt=`:** múltiplos canais (`cs2`, `valorant`, `lol`) e ingestão contínua (todo dia gera partição nova) exigem leitura seletiva e barata na camada Gold/dashboard — DuckDB/Polars leem só as partições relevantes em vez de escanear tudo.
- **Estratégia de cota da API:** nunca usa `search.list` (100 unidades/chamada). Usa `channels.list` (1x, pega playlist de uploads) + `playlistItems.list` (1 unidade/página, pagina até achar candidatos suficientes) + `videos.list` (1 unidade por lote de até 50 IDs, traz `snippet.publishedAt` confiável — o campo `contentDetails.videoPublishedAt` do `playlistItems` é instável e não é usado para filtrar).
- **Filtro de duração (`duracao_min_seg`)**: aplicado dentro do próprio `discovery.py`, cavando até 10 páginas (~500 candidatos) na playlist de uploads antes de desistir — necessário porque os canais de esports publicam muito mais shorts/clipes do que vídeo longo, e uma busca rasa não encontrava vídeo suficiente.
- **Throttle entre chamadas de transcrição (`transcript_delay_seg`)**: `youtube_transcript_api` bloqueia IP que faz rajada de requisições (`IpBlocked`) — especialmente relevante em rede compartilhada (laboratório/sala de aula). O ciclo espaça as chamadas em vez de disparar tudo de uma vez.
- **Frequência de ingestão por canal**: 60 min para os três canais — nenhum posta com frequência menor que isso, e evita gasto de cota desnecessário.
- **Por que "resultado comentado x audiência" em vez de densidade de jargão**: os canais são vlogs de bastidor/dia a dia (jogador conversando sobre aleatoriedades, treino, brincadeira), **não narração/transmissão** — termos de shoutcasting (`clutch`, `ace`, `virada`) nunca apareceriam em fala casual. A técnica de referência do domínio (`02_esportes_e_futebol.ipynb`) classifica cada trecho num "clima" (crise/positivo/neutro) e agrega por vídeo com Polars Lazy; aqui a adaptação é classificar o **vídeo inteiro** pelo resultado comentado (positivo/negativo/sem menção, usando vocabulário de fala casual em `config/sinais.yaml`) e cruzar com `view_count`/`like_count`/`comment_count` reais (persistidos no SQLite na descoberta) — respondendo se vídeo de vitória, derrota ou vlog puro engaja diferente.
- **Snapshot de audiência**: `view_count`/`like_count`/`comment_count` são gravados uma vez, no momento da descoberta (`INSERT ... ON CONFLICT DO NOTHING`) — não são atualizados depois. Aceitável para a janela de 7 dias de observação; documentado como limitação conhecida, não escondida.

## Princípios de engenharia (§4.2 — avaliados)

- **Idempotência:** cada vídeo é identificado por `video_id` + `content_hash` (SHA256 do texto da transcrição) no SQLite. Rodar o mesmo ciclo 2x não duplica: se o hash já foi ingerido, o vídeo é pulado (`pulados_idempotencia`); além disso, o watermark por canal (`last_published_at`) evita nem descobrir de novo vídeo já processado.
- **Tratamento de erro:** vídeo sem legenda → `marcar_falha("sem legenda")`, ciclo segue para o próximo. Falha de contrato Pandera → lote vai para `datalake/silver/_quarentena/` (inspecionável) e é registrado como falha no SQLite. Nenhuma falha individual derruba o ciclo inteiro.
- **Rastreabilidade:** cada `rodar_ciclo` retorna contadores explícitos (`descobertos`, `ingeridos`, `pulados_idempotencia`, `falhas`, `descartados_duracao`), logados e também consultáveis via `--status` (agregado do SQLite).
- **Observabilidade:** logs estruturados (`logging`, nível INFO) por ciclo/canal; `python -m ingestor.scheduler --status` resume o estado sem precisar abrir o VS Code; dashboard Streamlit expõe metadados de confiabilidade (última ingestão, descobertos, falhas).
