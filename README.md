# EsportsPulse

> Trabalho final da disciplina Linguagens de Programação para Engenharia de Dados — UNIFOR.
> Monitoramento automático de canais oficiais de organizações de esports (FURIA/LOUD/paiN),
> medindo densidade de sinais-chave (`clutch`, `virada`, `ace`, `polêmica`...) nos vídeos.
> Ver `docs/CARTA_DO_PROJETO.md` para problema, propósito e perguntas analíticas.

## Como rodar

```bash
# 1. ambiente (venv próprio deste projeto, isolado da disciplina)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configurar
cp .env.example .env            # preencher YOUTUBE_API_KEY (NÃO commitar)
$EDITOR config/canais.yaml      # canais reais do domínio (já preenchido para os 3 canais atuais)

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
projeto_template/
├── docs/
│   ├── CARTA_DO_PROJETO.md      # §3 — preencher e assinar
│   ├── ARQUITETURA.md           # §7.2 — diagrama + decisões
│   ├── RUNBOOK.md               # §7.2 — operar/reiniciar/logs
│   └── RELATORIO_7_DIAS.md      # §6 — observação em produção
├── config/
│   └── canais.yaml              # canais + intervalo por negócio (declarativo)
├── ingestor/                    # COPIAR do projeto_modelo (ver ingestor/README.md)
├── app/
│   └── streamlit_app.py         # dashboard de insights (lê Gold + controle)
├── deploy/
│   ├── ingestor.service         # systemd — ingestor perene
│   └── streamlit.service        # systemd — dashboard
├── datalake/                    # gerado em runtime (NÃO versionar)
├── requirements.txt
├── .env.example                 # sem segredos reais
├── .gitignore
└── README.md
```

## Checklist de entrega (§10)

```
[ ] Domínio confirmado e único na turma
[ ] docs/CARTA_DO_PROJETO.md assinada por todos
[ ] Pipeline Bronze → Silver → Gold executável
[ ] Contrato Pandera + pasta _quarentena funcionando
[ ] Watermark e idempotência no SQLite
[ ] Agendamento perene configurado
[ ] Streamlit publicado na VPS com URL estável
[ ] 7 dias de observação concluídos
[ ] docs/RELATORIO_7_DIAS.md com métricas e prints
[ ] README + RUNBOOK + ARQUITETURA completos
[ ] .env fora do Git; .env.example atualizado
[ ] Apresentação de 15 min preparada
```

## O que NÃO entregar

- ❌ Gold genérico (densidade de termos do template) — customize ao domínio (§7.3).
- ❌ `.env` no Git — nota zero no deploy (§9).
- ❌ Um único commit no último dia — o histórico precisa ser coerente (§7.1).
