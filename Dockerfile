# Dockerfile ÚNICO para os dois processos do projeto (ingestor + dashboard).
# A imagem é a mesma; o docker-compose.yml decide qual comando cada container roda.
# (§4 do contrato aceita "orquestrador documentado" — Docker/Coolify é o nosso.)

FROM python:3.11-slim

# Boas práticas: não gerar .pyc, log sem buffer (aparece na hora no painel do Coolify).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) Dependências primeiro (cache de build: só reinstala se requirements.txt mudar).
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 2) Código do projeto.
COPY . .

# 3) O datalake vive AQUI dentro (/app/datalake). O docker-compose monta um VOLUME
#    neste caminho, então os dados sobrevivem a cada redeploy (idempotência/§4.2).
#    Obs.: o pipeline grava em "./datalake" (relativo ao WORKDIR), e o dashboard lê
#    DATALAKE_DIR=/app/datalake — os dois apontam para o MESMO lugar.
RUN mkdir -p /app/datalake

# Porta do dashboard (documental; o compose expõe de fato).
EXPOSE 8501

# Sem CMD fixo: cada serviço no docker-compose.yml define seu próprio "command".
