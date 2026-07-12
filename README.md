# EsportsPulse

> Trabalho final da disciplina Linguagens de Programação para Engenharia de Dados — UNIFOR.
> Monitora os canais oficiais de organizações de esports (FURIA/LOUD/paiN Gaming/MIBR/Fluxo) e
> classifica cada vídeo por **tipo de conteúdo** (jogo vs. entretenimento genérico),
> pela **modalidade mencionada** (CS2/Valorant/LoL/Free Fire/R6 — detectada na própria
> transcrição, já que uma organização cobre várias modalidades no mesmo canal) e,
> quando é sobre o jogo, pelo **resultado comentado** (vitória/derrota) — cruzando tudo
> com audiência real (views, likes, comentários, inscritos) e com o texto real dos
> comentários do público, tanto **dentro de cada organização** quanto **entre elas**.
> Ver `docs/CARTA_DO_PROJETO.md` para problema, propósito e perguntas analíticas.

## Como rodar

```bash
# 1. ambiente (venv próprio deste projeto)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configurar
cp .env.example .env            # preencher YOUTUBE_API_KEY (NÃO commitar)
$EDITOR config/canais.yaml      # canais institucionais (já preenchido para FURIA/LOUD/paiN/MIBR/Fluxo)

# 3. rodar
python -m ingestor.scheduler --once      # 1 ciclo
python -m ingestor.scheduler --status    # observabilidade
python -m ingestor.scheduler             # perene (agendado por canal)
streamlit run app/streamlit_app.py       # dashboard em http://localhost:8501
```

Detalhes de operação (start/stop/logs/troubleshooting): `docs/RUNBOOK.md`.
Decisões técnicas e diagrama: `docs/ARQUITETURA.md`.

## Estrutura

```
esportspulse/
├── docs/
│   ├── CARTA_DO_PROJETO.md      # §3 — problema, propósito, perguntas analíticas
│   ├── ARQUITETURA.md           # §7.2 — diagrama + decisões técnicas
│   ├── RUNBOOK.md               # §7.2 — operar/reiniciar/logs/troubleshooting
│   └── RELATORIO_7_DIAS.md      # §6 — preencher após a observação em produção
├── config/
│   ├── canais.yaml              # canais institucionais (1 canal = 1 organização, não 1 jogo), intervalo
│   └── sinais.yaml              # vocabulário: contexto de jogo, resultado positivo/negativo, jogos (por vídeo)
├── ingestor/                    # pipeline real (discovery/state/transcript/pipeline/scheduler)
├── app/
│   ├── streamlit_app.py         # entrypoint: navegação entre as 3 páginas
│   ├── common.py                # paleta, loaders cacheados, helpers de UI (hero, nuvem de palavras)
│   ├── paginas/
│   │   ├── geral.py             # página Geral — visão de mercado (todas as orgs agregadas)
│   │   ├── por_time.py          # página Por Time — intra-organização (com seletor)
│   │   └── cross.py             # página Cross-Org — comparação entre organizações
│   └── assets/                  # logos das organizações
├── deploy/
│   ├── ingestor.service         # systemd — ingestor perene
│   └── streamlit.service        # systemd — dashboard
├── datalake/                    # gerado em runtime (NÃO versionado — ver .gitignore)
├── requirements.txt
├── .env.example                 # sem segredos reais
├── .gitignore
└── README.md
```

## Checklist de entrega (§10)

```
[?] Domínio confirmado e único na turma — depende de confirmação com o professor
[x] docs/CARTA_DO_PROJETO.md assinada
[x] Pipeline Bronze → Silver → Gold executável — testado com dado real
[x] Contrato Pandera + pasta _quarentena funcionando — testado
[x] Watermark e idempotência no SQLite — testado
[x] Agendamento perene configurado — testado (APScheduler, ciclos automáticos)
[ ] Streamlit publicado na VPS com URL estável — falta deploy na VPS
[ ] 7 dias de observação concluídos — inicia após o deploy
[ ] docs/RELATORIO_7_DIAS.md com métricas e prints — preencher após a observação
[x] README + RUNBOOK + ARQUITETURA completos
[x] .env fora do Git; .env.example atualizado
[ ] Apresentação de 15 min preparada
```

## O que NÃO entregar

- ❌ Gold genérico (densidade de termos do template) — customizado ao domínio: classificação em dois níveis (tipo de conteúdo → resultado) cruzada com audiência real (§7.3).
- ❌ `.env` no Git — nota zero no deploy (§9).
- ❌ Um único commit no último dia — o histórico precisa ser coerente (§7.1).
