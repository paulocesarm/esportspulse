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
| `youtube_transcript_api.IpBlocked`/`RequestBlocked` (todas as transcrições falham, mesmo vídeo que funcionou antes) | Rajada de requisições — o IP (às vezes compartilhado, ex. rede de laboratório **ou VPS/cloud**, que o próprio erro da lib avisa que costuma ser bloqueado) levou bloqueio temporário do YouTube. Um `sleep`/delay entre chamada **não desbloqueia** um IP já bloqueado — só evita causar o bloqueio | **Não precisa apagar `datalake/` nem rodar de novo na mão.** Desde 2026-07 existe um handler de verdade (`ingestor/state.py:registrar_bloqueio`/`get_cooldown`, chamado em `pipeline.py:rodar_ciclo`): ao levar `RequestBlocked`, o canal fica em **cooldown persistido no SQLite** com backoff exponencial (15min → 30min → 1h → 2h teto, `global.transcript_cooldown_base_seg`/`transcript_cooldown_max_seg`) — o **próximo** `--once`/ciclo agendado pula esse canal inteiro (nem tenta) até o prazo passar, e loga isso (`"<canal> em cooldown até ..."`). O contador zera assim que 1 vídeo daquele canal ingerir com sucesso. Se o bloqueio for muito frequente mesmo assim: reduzir `max_videos_por_ciclo` (rajada menor); considerar proxy (`youtube_transcript_api` suporta `WebshareProxyConfig`) se a VPS de produção tiver IP de datacenter bloqueado com frequência — fora do escopo deste projeto, mas é a solução "de produção" real pra esse problema |
| Muitos vídeos descartados por duração (`descartados_duracao` alto) | Canal posta muita coisa curta (shorts/clipes) | esperado — ajustar `duracao_min_seg` no `canais.yaml` se quiser incluir/excluir vídeos curtos |
| Canal recém-ativado (`ativo: true`) traz poucos vídeos mesmo tendo espaço em `max_videos_por_ciclo` | Sem histórico suficiente dentro de `janela_descoberta_dias` | Esperado — a descoberta usa sempre exatamente `max_videos_por_ciclo`/`janela_descoberta_dias` de `canais.yaml`, sem escalonar a janela sozinha. Se quiser mais histórico, aumente `janela_descoberta_dias` manualmente |
| Volume muito diferente entre organizações (ex. 20 vídeos da FURIA vs. 2 do LOUD) enviesando a comparação Cross-Org | `max_videos_por_ciclo` alto (25) deixava cada canal crescer sem limite comparável, e o volume real dependia de quanto cada canal conseguia ingerir antes de um bloqueio de IP interromper o ciclo | Reduzido pra `max_videos_por_ciclo: 10` em todos os canais — teto igual pra todos, então a comparação passa a ser sobre um volume parecido, não sobre "quem não travou primeiro" |
| Dashboard **crasha o processo inteiro** (segfault, sem traceback Python) ao trocar de canal | Bug real de `pandas 3.0.3` + `pyarrow 25.0.0` na conversão pra Arrow usada por `st.bar_chart`/`st.dataframe` (reproduzido com `faulthandler`) | garantir que o `.venv` tem as versões fixadas no `requirements.txt` (`pandas<3.0`, `pyarrow<18.0`); se instalou antes dessa correção, rode `pip install -r requirements.txt` de novo pra baixar a versão certa |
| Poucos vídeos com resultado detectado (`categoria` = `indefinido` na maioria) | Bug antigo (já corrigido) na limpeza de texto: acentos viravam espaço e quebravam palavras (`vitória` → `vit ria`, nunca batia com `vitoria` no `sinais.yaml`) | já corrigido em `_limpar()` (normalização Unicode antes de filtrar caracteres); se ainda acontecer, reprocessar a Silver a partir da Bronze (não precisa rechamar a API) |
| Poucos vídeos com **modalidade** detectada (`jogo_detectado` = `indefinido` mesmo em canal 100% de um jogo só, ex. FURIA/CS2) | Bug real (corrigido em 2026-07): a limpeza de texto usada pra detecção removia dígito (`"cs2"` virava `"cs"`, `"r6"` virava `"r"`), nunca batendo com `config/sinais.yaml`. Corrigido com `_normalizar_deteccao()` (mantém dígito) + coluna nova `texto_deteccao` no Silver + sinal extra de nomes de jogador por canal (`sinais.yaml:elencos`) | dado antigo (ingerido antes da correção) precisa reprocessar: `python -m ingestor.scripts.reprocessar_silver_gold` (lê o Bronze já capturado, não rechama a API). Resíduo aceito: vídeo tipo vlog de bastidor que não cita o jogo nem o elenco explicitamente continua `indefinido` — limite do classificador por palavra-chave, não 100% resolvido |
| Site abre com fundo escuro/preto, logo (ex. MIBR) some | Sem `.streamlit/config.toml`, o tema seguia o SO/navegador de quem acessava | corrigido: `.streamlit/config.toml` fixa `theme.base = "light"` como padrão |

## Contatos do time

| Papel | Nome | Contato |
|---|---|---|
| Eng. dados / qualidade / deploy / produto | Paulo Cesar | paulocesarmlf@gmail.com |
