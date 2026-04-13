# Andreia — Agente IA Residere

Agente conversacional de WhatsApp baseado em IA para qualificação e atendimento de leads imobiliários da **Residere Imóveis**.

## Visão Geral

A Andreia é um agente autônomo que atende leads via WhatsApp, conduz fluxos de qualificação (compra, venda, locação, investimento, lançamentos e permuta), integra com CRM (Kommo), envia e-mails e agenda follow-ups automáticos.

```
WhatsApp (UAZAPI)
       │
       ▼
  API (FastAPI) ──► RabbitMQ ──► Worker (LangGraph + Scheduler)
       │                                │
       └──────────── PostgreSQL ◄───────┘
                         │
                    ChromaDB (RAG)
```

## Arquitetura dos Serviços

| Serviço | Tecnologia | Responsabilidade |
|---------|-----------|-----------------|
| **api** | FastAPI + Uvicorn | Recebe webhooks do WhatsApp e publica na fila |
| **worker** | Python + aio-pika | Consome mensagens, executa o agente e roda o scheduler |
| **postgres** | PostgreSQL 16 | Persistência de leads, conversas e jobs agendados |
| **rabbitmq** | RabbitMQ 3 | Desacoplamento entre API e processamento do agente |

## Fluxos do Agente

- **Comprador** — Qualificação de perfil, orçamento e urgência
- **Investidor** — Scoring QUENTE / MORNO / FRIO com identificação de barreira (financeira, timing, conhecimento)
- **Locação** — Atendimento de interessados em aluguel
- **Venda** — Captação de imóveis
- **Lançamentos** — Apresentação de novos empreendimentos
- **Permuta** — Troca de imóveis
- **FAQ / Off-topic** — Respostas com base na knowledge base (RAG)

## Integrações

- **UAZAPI** — Envio e recebimento de mensagens WhatsApp
- **Kommo CRM** — Criação e atualização de negócios por estágio
- **E-mail** — Notificações para corretores e leads (SMTP)
- **Sistema de Agenda** — Agendamento de visitas
- **LangSmith** — Tracing e observabilidade do agente

## Pré-requisitos

- Docker e Docker Compose
- Conta UAZAPI com instância WhatsApp ativa
- Conta Kommo CRM com pipeline configurado
- Chave de API OpenAI

## Configuração

```bash
cp .env.example .env
# Edite o .env com suas credenciais
```

Variáveis obrigatórias:

```env
POSTGRES_PASSWORD=         # senha do banco
RABBITMQ_PASSWORD=         # senha do RabbitMQ
OPENAI_API_KEY=            # sk-...
UAZAPI_BASE_URL=           # https://sua-instancia.uazapi.com
UAZAPI_TOKEN=              # token da instância
UAZAPI_INSTANCE_ID=        # ID da instância
WEBHOOK_SECRET=            # segredo para validar webhooks
KOMMO_SUBDOMAIN=           # ex: "suaempresa"
KOMMO_ACCESS_TOKEN=        # token de longa duração do Kommo
KOMMO_PIPELINE_ID=         # ID do pipeline
KOMMO_STAGE_MAP=           # JSON com mapeamento de stages
JWT_SECRET_KEY=            # chave secreta para JWT
```

## Rodando com Docker

```bash
docker compose up -d
```

Os serviços sobem na seguinte ordem:
1. `postgres` e `rabbitmq` (com healthcheck)
2. `migration` — executa `alembic upgrade head` e encerra
3. `api` e `worker` — sobem após a migration concluir

A API fica disponível em `http://localhost:8000`.

## Rodando Localmente (desenvolvimento)

```bash
python -m venv .venv
source .venv/bin/activate      # Linux/Mac
.venv\Scripts\activate         # Windows

pip install -r requirements.txt

# Sobe apenas a infra
docker compose up postgres rabbitmq -d

# Aplica migrations
alembic upgrade head

# Ingere a base de conhecimento (primeira vez)
python scripts/ingest_knowledge.py

# Terminal 1 — API
uvicorn src.api.main:app --reload

# Terminal 2 — Worker
python worker.py
```

## Estrutura do Projeto

```
agent-residere/
├── src/
│   ├── agent/          # LangGraph — nós, edges e estado
│   ├── api/            # FastAPI — rotas e webhook
│   ├── config/         # Settings (Pydantic)
│   ├── db/             # SQLAlchemy + Alembic migrations
│   ├── jobs/           # Scheduler de follow-ups e reengajamentos
│   ├── knowledge/      # Ingestão e busca vetorial (ChromaDB)
│   ├── media/          # Áudio (Whisper), PDFs, imagens
│   ├── properties/     # Catálogo de imóveis
│   ├── queue/          # RabbitMQ consumer/producer
│   ├── services/       # Lógica de negócio e integrações
│   └── utils/          # Logger, datetime, helpers
├── scripts/            # Utilitários de inicialização
├── tests/              # Testes unitários e de fluxo
├── worker.py           # Entrypoint do processo Worker
├── Dockerfile
└── docker-compose.yml
```

## Jobs Agendados

O scheduler consulta o banco a cada 60 segundos e executa os jobs pendentes:

| Tipo | Disparo | Descrição |
|------|---------|-----------|
| `timeout_5m` | 5 min sem resposta | Mensagem de reativação imediata |
| `timeout_30m` | 30 min sem resposta | Segunda tentativa |
| `reengagement_24h` | 24h sem resposta | Reengajamento do dia seguinte |
| `reengagement_7d` | 7 dias | Reengajamento semanal |
| `follow_up_48h` | 48h após interesse | Follow-up de comprador/locatário |
| `investor_quente` | Configurável | Nutrimento de investidor quente |
| `investor_nurture` | 30/60/90 dias | Nutrimento de longo prazo (FRIO) |
| `reminder_24h` | 24h antes da visita | Lembrete de agendamento |

> Os jobs verificam `last_lead_message_at` antes de disparar — se o lead já respondeu após o agendamento do job, ele é ignorado.

## Deploy no EasyPanel

1. Crie um novo projeto no EasyPanel
2. Adicione a source via repositório Git (este repo)
3. O EasyPanel usará o `docker-compose.yml` automaticamente
4. Configure todas as variáveis de ambiente na interface do EasyPanel (aba _Environment_)
5. Não é necessário arquivo `.env` no servidor — as variáveis são injetadas pelo EasyPanel

## Endpoints Principais

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/webhook/whatsapp` | Recebe mensagens do WhatsApp |
| `GET` | `/health` | Health check |
| `POST` | `/auth/login` | Autenticação JWT |
| `GET` | `/metrics` | Métricas do agente |
| `POST` | `/chat/test` | Chat de teste (sem WhatsApp) |

## Licença

Proprietário — Residere Imóveis / itech360
