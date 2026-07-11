# Carta do Projeto

> Template da §3 do `CONTRATO_TRABALHO_FINAL.md`. Preencha todos os campos.
> **Assinada por todos os integrantes** (nome + e-mail) ao final. Vale 10% da nota.

## 3.1 Identidade

| Campo | Preenchimento |
|---|---|
| **Nome do projeto** | EsportsPulse |
| **Tema / domínio** | Esportes & Futebol (adaptado para eSports — org. de esports: CS2, Valorant, LoL) |
| **Equipe** | Paulo Cesar — eng. dados, qualidade, deploy e produto (projeto individual) |
| **Data de início** | 2026-07-09 |

## 3.2 Problema e propósito

| Campo | Preenchimento |
|---|---|
| **Problema** | Os canais oficiais das organizações de esports são majoritariamente **vlogs de bastidor/dia a dia** — jogadores conversando sobre aleatoriedades, rotina, treino — e só em um ponto específico do vídeo (às vezes nenhum) comentam o resultado da partida. Hoje a organização não tem como saber, sem assistir vídeo a vídeo, se esse tipo de conteúdo (vitória, derrota, ou vlog sem menção ao jogo) engaja mais ou menos a audiência. |
| **Propósito** | Classificar automaticamente cada vídeo pelo resultado que comenta (vitória / derrota / sem menção — vlog puro) e cruzar essa classificação com métricas reais de audiência (visualizações, curtidas, comentários), sem precisar assistir cada vídeo manualmente. |
| **Público-alvo** | Organizações de esports (áreas de mídia, conteúdo e comunicação). |
| **Hipótese de valor** | Se cruzarmos o resultado comentado em cada vídeo (vitória/derrota/sem menção) com suas métricas de audiência, conseguimos identificar em horas — não dias — que tipo de conteúdo realmente engaja mais, orientando a organização sobre que ângulo explorar nos próximos vlogs (e se vale mais a pena reforçar o vídeo de vitória, ou se o conteúdo aleatório de bastidor já performa igual ou melhor). |

## 3.3 Escopo técnico

| Campo | Preenchimento |
|---|---|
| **Fontes de dados** | Canais oficiais no YouTube: FURIA eSports (`@FURIAgg`, domínio `cs2`), LOUD (`@loudgg`, domínio `valorant`), paiN Gaming (`@paingamingbr`, domínio `lol`). Vocabulário de resultado (fala casual, não jargão de narração) em `config/sinais.yaml`: positivo (`ganhamos`, `vencemos`, `vitoria`, `campeao`...) e negativo (`perdemos`, `derrota`, `eliminados`...). Idiomas de legenda: `pt`, `pt-BR`, `en` (fallback). |
| **Frequência de ingestão** | 60 min para os três canais — nenhum posta com frequência menor que isso; evita gasto de cota sem necessidade. |
| **Métrica principal (KPI)** | Média de visualizações (e curtidas/comentários) por categoria de vídeo: vitória comentada vs. derrota comentada vs. sem menção ao resultado (vlog puro). |
| **Perguntas analíticas** | Ver lista abaixo (mínimo 3). |
| **Fora de escopo** | Análise de sentimento profunda (NLP avançado além da classificação por palavra-sinal), monitoramento de outras redes sociais além do YouTube, tradução automática fora de pt/pt-BR/en, classificação automática de "tipo de vídeo" além do proxy `category_id` do YouTube. |

### Perguntas analíticas (mínimo 3)

1. Vídeos que comentam **vitória** têm mais visualizações/curtidas/comentários do que os que comentam **derrota**, ou do que o vlog **sem menção** ao resultado?
2. Qual canal (FURIA/LOUD/paiN) tem a maior diferença de audiência entre vídeo de vitória e vídeo de derrota?
3. Como a proporção de vídeos "sem menção ao resultado" (puro conteúdo de bastidor) se compara, em audiência média, aos vídeos que efetivamente falam do jogo?
4. (bônus) Vídeos de categorias do YouTube (`category_id`) diferentes do padrão do canal têm engajamento diferente — indício de que fugir do formato vlog tradicional muda a audiência?

## 3.4 Critérios de sucesso

| Campo | Preenchimento |
|---|---|
| **Definição de pronto** | Ingestor roda sozinho no intervalo configurado sem intervenção manual; idempotência comprovada (rodar N vezes não duplica); Gold cruza classificação de resultado com métricas reais de audiência; dashboard publicado refletindo dado real; 7 dias de observação concluídos com métricas registradas. |
| **Riscos** | (1) Cota da API esgotar — mitigado pela estratégia de baixo custo (channels.list + playlistItems.list + videos.list, ~2 unidades/canal/ciclo). (2) Vídeo sem legenda em pt/pt-BR/en — pipeline marca falha e segue para o próximo vídeo, não trava o ciclo. (3) `youtube_transcript_api` sofrer bloqueio de IP (`IpBlocked`) — já observado em rede compartilhada (sala com vários alunos no mesmo IP); mitigado com `transcript_delay_seg` (throttle) e `max_videos_por_ciclo` conservador. (4) Vocabulário de resultado (`sinais.yaml`) não capturar a forma real como os jogadores falam (é fala casual, não roteirizada) — mitigado revisando o vocabulário à luz de transcrições reais assim que a ingestão rodar sem bloqueio. (5) `view_count`/`like_count` são um snapshot do momento da descoberta (não atualizam depois) — aceitável para a janela de 7 dias de observação, mas não reflete audiência futura do mesmo vídeo. (6) Canal com muito conteúdo curto (shorts/clipes) — filtro `duracao_min_seg` descarta, mas pode reduzir o volume ingerido em canais que postam majoritariamente conteúdo curto. |

---

## Assinaturas

| Integrante | E-mail | Papel |
|---|---|---|
| Paulo Cesar | paulo.cesar@memed.com.br | Eng. de dados / qualidade / deploy / produto |
