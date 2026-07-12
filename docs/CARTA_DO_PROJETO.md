# Carta do Projeto

> Template da §3 do `CONTRATO_TRABALHO_FINAL.md`. Preencha todos os campos.
> **Assinada por todos os integrantes** (nome + e-mail) ao final. Vale 10% da nota.

## 3.1 Identidade

| Campo | Preenchimento |
|---|---|
| **Nome do projeto** | EsportsPulse |
| **Tema / domínio** | Esportes & Futebol (adaptado para eSports — organizações institucionais que cobrem várias modalidades: CS2, Valorant, LoL, Free Fire, R6) |
| **Equipe** | Paulo Cesar — eng. dados, qualidade, deploy e produto (projeto individual) |
| **Data de início** | 2026-07-09 |

## 3.2 Problema e propósito

| Campo | Preenchimento |
|---|---|
| **Problema** | Os canais oficiais das organizações de esports misturam **conteúdo sobre o jogo** (vlogs de torneio, resultado de partida) com **entretenimento genérico sem nenhuma relação com o jogo** (desafios, casas assombradas) — e cada canal institucional cobre **várias modalidades** (CS2, Valorant, LoL...), não uma só. Hoje a organização não sabe, sem assistir vídeo a vídeo, que tipo de conteúdo e qual modalidade realmente engajam, nem como isso se compara com as demais organizações do mercado, nem o que a própria torcida está comentando. |
| **Propósito** | Classificar automaticamente cada vídeo por **tipo** (jogo vs. entretenimento), pela **modalidade mencionada** (detectada na transcrição, não fixada por canal) e, quando for sobre o jogo, pelo **resultado comentado** (vitória/derrota) — cruzando com métricas reais de audiência (views, likes, comentários) e com o **texto real dos comentários do público**, tanto **dentro de cada organização** quanto **entre as organizações** (normalizado por número de inscritos). |
| **Público-alvo** | Organizações de esports (áreas de mídia, conteúdo e comunicação). |
| **Hipótese de valor** | Se classificarmos cada vídeo por tipo de conteúdo, modalidade e resultado, e cruzarmos com audiência normalizada por inscritos e com o que a torcida comenta, conseguimos responder em horas — não dias — que tipo de conteúdo e modalidade realmente performam (dentro da organização) e como cada organização se compara às demais (entre organizações), mesmo quando o tamanho da audiência é muito diferente entre elas. |

## 3.3 Escopo técnico

| Campo | Preenchimento |
|---|---|
| **Fontes de dados** | Canais oficiais no YouTube (domínio institucional único `esports`): FURIA eSports (`@FURIAgg`), LOUD (`@loudgg`), paiN Gaming (`@paingamingbr`). Vocabulário em `config/sinais.yaml`, em três níveis: `contexto_jogo` (termos inequívocos de torneio/partida — `campeonato`, `torneio`, `playoffs`, `major`...), `resultado_positivo`/`resultado_negativo` (fala casual de vitória/derrota, aplicado só dentro de vídeo já classificado como "jogo") e `jogos` (frases que identificam a modalidade — `cs2`, `valorant`, `league of legends`... — detectadas por vídeo, não por canal). Métricas de canal (inscritos, views totais) via `channels.list(part=statistics)`. Texto real dos comentários via `commentThreads.list` (amostra por relevância, base da nuvem de palavras). Idiomas de legenda: `pt`, `pt-BR`, `en` (fallback). |
| **Frequência de ingestão** | 1x/dia para todos os canais — nenhum posta mais de 1-2 vídeos/dia; evita gasto de cota sem necessidade. |
| **Métrica principal (KPI)** | Alcance relativo (views médias ÷ inscritos) por organização — normaliza a comparação entre canais de tamanhos de audiência muito diferentes (ex.: LOUD tem 13M de inscritos contra 106 mil da FURIA). |
| **Perguntas analíticas** | Ver lista abaixo (mínimo 3). |
| **Fora de escopo** | Audience retention / tempo de visualização (`watch time`) — só existe via YouTube Analytics API com OAuth do **dono do canal**; como monitoramos canais de terceiros, essa métrica é inacessível. Também fora de escopo: análise de sentimento profunda (NLP além da classificação por palavra-sinal), monitoramento de redes sociais além do YouTube, tradução automática fora de pt/pt-BR/en. |

### Perguntas analíticas (mínimo 3)

1. **Intra-canal**: dentro de cada organização, vídeo sobre o jogo engaja mais ou menos que vídeo de entretenimento genérico? E, dentro dos vídeos sobre o jogo, vitória engaja mais que derrota?
2. **Cross-org**: qual organização tem o maior "alcance relativo" (views médias ÷ inscritos) — ou seja, qual converte melhor sua base de inscritos em audiência ativa por vídeo?
3. **Cross-org**: qual organização concentra mais conteúdo sobre o jogo (% de vídeos tipo "jogo") vs. entretenimento genérico, e isso se relaciona com o alcance relativo?
4. **Cross-org**: em qual modalidade (CS2/Valorant/LoL/...) cada organização concentra mais conteúdo — o canal institucional reflete uma modalidade dominante ou é disperso entre várias?
5. (bônus) Vídeos de `category_id` do YouTube diferente do padrão do canal têm engajamento diferente — indício de que fugir do formato tradicional muda a audiência?

## 3.4 Critérios de sucesso

| Campo | Preenchimento |
|---|---|
| **Definição de pronto** | Ingestor roda sozinho no intervalo configurado sem intervenção manual; idempotência comprovada (rodar N vezes não duplica); Gold classifica tipo+modalidade+resultado e cruza com audiência real e com o comentário do público (intra e cross-org); dashboard publicado com as 3 páginas (Geral, Por Time, Cross-Org); 7 dias de observação concluídos com métricas registradas. |
| **Riscos** | (1) Cota da API esgotar — mitigado pela estratégia de baixo custo (channels.list + playlistItems.list + videos.list, ~3 unidades/canal/ciclo). (2) Vídeo sem legenda em pt/pt-BR/en — pipeline marca falha e segue para o próximo vídeo, não trava o ciclo. (3) `youtube_transcript_api` sofrer bloqueio de IP (`IpBlocked`) — já observado de fato em rede compartilhada (sala de aula, várias pessoas no mesmo IP); mitigado com throttle fixo de 2s entre chamadas e `max_videos_por_ciclo` conservador; validado que funciona normalmente em outra rede (ex.: 4G/5G). (4) Vocabulário (`sinais.yaml`) gerar falso positivo — já aconteceu e foi corrigido: palavras genéricas como "jogo" e "final" apareciam em conversa casual sem relação com a partida (ex.: "no final das contas"); resolvido restringindo `contexto_jogo` a termos inequívocos de torneio. Resíduo aceito: distinguir "partida real da organização" de "rodada de gameplay sendo analisada" (canal paiN) é ambíguo e não 100% resolvido por palavra-chave. (5) `view_count`/`like_count`/inscritos são snapshot do momento da coleta, não atualizam automaticamente depois — aceitável para a janela de 7 dias. (6) Canal com muito conteúdo curto (shorts/clipes) — filtro `duracao_min_seg` descarta, mas pode reduzir o volume ingerido em canais que postam majoritariamente conteúdo curto. |

---

## Assinaturas

| Integrante | E-mail | Papel |
|---|---|---|
| Paulo Cesar | paulocesarmlf@gmail.com | Eng. de dados / qualidade / deploy / produto |
