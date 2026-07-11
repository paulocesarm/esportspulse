# Runbook — Operação

> Template da §7.2. Como operar, reiniciar e ler logs. **Obrigatório** (§9: sem RUNBOOK = −5%).

## Pré-requisitos

- Python 3.11+, venv criado (`.venv`) com `requirements.txt` instalado.
- `.env` preenchido (a partir de `.env.example`) — **na VPS**, fora do Git.

## Rodar localmente

```bash
source .venv/bin/activate
python -m ingestor.scheduler --once      # 1 ciclo
python -m ingestor.scheduler --status    # estado atual
python -m ingestor.scheduler             # perene (agendado)
streamlit run app/streamlit_app.py       # dashboard em http://localhost:8501
```

## Produção (VPS — systemd)

**Iniciar / habilitar no boot**
```bash
sudo cp deploy/ingestor.service  /etc/systemd/system/
sudo cp deploy/streamlit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ingestor streamlit
```

**Status**
```bash
systemctl status ingestor streamlit
python -m ingestor.scheduler --status
```

**Parar / reiniciar**
```bash
sudo systemctl restart ingestor
sudo systemctl stop streamlit
```

**Logs (observabilidade)**
```bash
journalctl -u ingestor -f          # tempo real
journalctl -u ingestor --since "1 hour ago"
```

## Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `descobertos: 0` no 1º ciclo | watermark antigo | conferir estado; se em teste, limpar `datalake/` |
| Gold vazio | sem Silver / vocabulário não bate | inspecionar Silver antes do Gold |
| erro de cota da API | intervalo curto / muitos canais | aumentar `intervalo_min`; conferir estratégia de cota |
| dashboard fora do ar | serviço streamlit caído | `systemctl restart streamlit`; ver `journalctl -u streamlit` |
| `ModuleNotFoundError` | venv não ativo | ativar `.venv` ou usar o caminho absoluto do python |
| `google.auth.exceptions.DefaultCredentialsError` | `YOUTUBE_API_KEY` não chegou ao processo (kernel/serviço não carregou o `.env`) | conferir se `.env` existe e tem a chave; local usa `python-dotenv` (automático no `scheduler.py`); na VPS conferir `EnvironmentFile=` no `.service` |
| `youtube_transcript_api.IpBlocked` (todas as transcrições falham, mesmo vídeo que funcionou antes) | Rajada de requisições — o IP (às vezes compartilhado, ex. rede de laboratório) levou bloqueio temporário do YouTube | esperar (minutos a horas); reduzir `max_videos_por_ciclo`; aumentar `transcript_delay_seg` em `config/canais.yaml` |
| Muitos vídeos descartados por duração (`descartados_duracao` alto) | Canal posta muita coisa curta (shorts/clipes) | esperado — ajustar `duracao_min_seg` no `canais.yaml` se quiser incluir/excluir vídeos curtos |

## Contatos do time

| Papel | Nome | Contato |
|---|---|---|
| Eng. dados / qualidade / deploy / produto | Paulo Cesar | paulo.cesar@memed.com.br |
