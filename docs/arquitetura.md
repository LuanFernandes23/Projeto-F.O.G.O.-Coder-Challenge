# Arquitetura — F.O.G.O.

## Visão geral

```mermaid
flowchart LR
    Front[Front-end / Swagger] -->|HTTP + JWT| API
    subgraph Backend [backend/app]
        API[api/routes<br/>validação + RBAC] --> SVC[services<br/>casos de uso]
        SVC --> DOM[domain<br/>regras puras]
        SVC --> PORTS[[ports<br/>interfaces]]
        REPO[repositories<br/>SQLAlchemy + PostGIS] -. implementa .-> PORTS
        SVC --> INT[integrations<br/>ViaCEP / BrasilAPI]
        JOB[jobs/scheduler<br/>APScheduler] --> SVC
    end
    REPO --> PG[(PostgreSQL 16<br/>+ PostGIS)]
    INT -->|httpx, timeout 3s| EXT((APIs de CEP))
```

- **Rotas** só convertem HTTP ↔ contratos Pydantic e declaram a permissão exigida (`Requires(Permission.X)`).
- **Serviços** orquestram uma operação inteira dentro de **uma** unidade de trabalho (`async with uow` → `commit`). Qualquer exceção leva a rollback.
- **Domínio** não conhece banco nem HTTP: máquina de estados, política de manutenção e regras de agentes são funções puras, testadas exaustivamente.
- **Repositórios** são o único lugar com SQL. Eles convertem as linhas em objetos de domínio (Data Mapper), e os serviços dependem só das **portas** (`services/ports.py`). Por isso os testes unitários usam repositórios em memória.
- **Integrações** externas ficam isoladas: o serviço de endereço recebe uma lista de provedores e tenta um após o outro.
- Nada é criado no import: engine, pool e cliente HTTP nascem no `lifespan` (`create_app()` é uma factory).

## Modelo de dados

```mermaid
erDiagram
    organizations ||--o{ equipment : "responsável"
    organizations ||--o{ agents : "lotação"
    equipment_types ||--o{ equipment : "tipo"
    regions ||--o{ equipment : "região (ST_Covers)"
    regions ||--o{ agents : "região da base"
    equipment ||--o{ equipment_status_history : "histórico"
    equipment ||--o| maintenance_plans : "plano periódico"
    equipment ||--o{ maintenance_orders : "ordens"
    equipment ||--o{ agents : "viatura atribuída"
    agents ||--o{ agent_status_history : "histórico"
    users ||--o{ equipment_status_history : "alterado por"

    equipment {
        uuid id PK
        string type_code FK
        string serial_number "UNIQUE(lower(brand), lower(serial)) WHERE ativo"
        string brand
        string model
        uuid organization_id FK
        string status "máquina de estados"
        string cep
        string street
        string address_reference "texto livre: 181, KM 203, S/N..."
        string neighborhood
        string city
        string uf
        geography location "POINT 4326 + GIST"
        uuid region_id FK
        date installed_on
        jsonb attributes "validado por schema do tipo + GIN"
        string maintenance_need "desnormalizado"
        date next_maintenance_date "desnormalizado + índice"
        int version "lock otimista"
        timestamptz archived_at "soft delete"
    }
    equipment_types {
        string code PK
        string category
        string icon
        bool is_mobile
        bool is_vehicle
        string attributes_schema_key
    }
    maintenance_orders {
        uuid id PK
        string kind "corretiva | preventiva"
        string priority "imediata | agendada"
        string status "aberta | em_andamento | concluida | cancelada"
        date scheduled_for
    }
    agents {
        uuid id PK
        string registration_number "UNIQUE por órgão"
        string role
        string duty_status
        geography location "base de lotação"
        uuid assigned_vehicle_id FK
        int version
    }
```

Os enums são guardados como `VARCHAR + CHECK`, o que permite evoluir sem `ALTER TYPE`. Todas as datas usam `timestamptz`, e as datas de calendário (`installed_on`, vencimentos) seguem o fuso `America/Sao_Paulo`.

## Máquina de estados do equipamento

```mermaid
stateDiagram-v2
    [*] --> nao_instalado
    [*] --> operacional
    [*] --> mau_funcionamento
    [*] --> desativado
    nao_instalado --> operacional : instalação
    nao_instalado --> desativado
    operacional --> mau_funcionamento : falha (abre OS imediata)
    operacional --> em_manutencao
    operacional --> desativado
    operacional --> furtado
    mau_funcionamento --> em_manutencao : OS iniciada
    mau_funcionamento --> operacional
    mau_funcionamento --> desativado
    mau_funcionamento --> furtado
    em_manutencao --> operacional : OS concluída
    em_manutencao --> mau_funcionamento
    em_manutencao --> desativado
    desativado --> em_manutencao
    desativado --> operacional : reativação
    furtado --> nao_instalado : recuperado
    furtado --> desativado : baixa
```

Uma transição fora do diagrama retorna `409 transicao_de_situacao_invalida` com a lista `allowed_transitions`. As saídas de `[*]` representam as situações aceitas no cadastro inicial.

## Fluxo de manutenção (automações)

```mermaid
sequenceDiagram
    actor Op as Operador
    participant API
    participant Life as EquipmentLifecycle
    participant DB as PostgreSQL

    Op->>API: POST /equipment/{id}/status-changes (mau_funcionamento)
    API->>Life: change_status
    Life->>DB: histórico + situação
    Life->>DB: abre OS corretiva IMEDIATA (se não houver)
    Life->>DB: recalcula necessidade/próxima data
    Op->>API: PATCH /maintenance-orders/{os} (em_andamento)
    API->>Life: equipamento → em_manutencao (com histórico)
    Op->>API: PATCH /maintenance-orders/{os} (concluida)
    API->>Life: equipamento → operacional, exceto se outra OS segue em andamento
    Note over API,DB: Concluir uma preventiva recalcula plan.next_due_date = hoje + intervalo
    Note over API,DB: Job diário (scheduler, com advisory lock) abre preventivas vencidas
```

Todos os passos de uma mesma requisição acontecem na **mesma transação**.

## Segurança e autorização

| Permissão | consulta | operador | gestor | admin |
|---|:-:|:-:|:-:|:-:|
| ler equipamentos, agentes e órgãos | ✅ | ✅ | ✅ | ✅ |
| mudar situação de equipamento ou agente | | ✅ | ✅ | ✅ |
| operar ordens de manutenção | | ✅ | ✅ | ✅ |
| cadastrar/editar/excluir equipamentos e agentes | | | ✅ | ✅ |
| planos de manutenção, órgãos e tipos | | | ✅ | ✅ |
| gerenciar usuários | | | | ✅ |

A matriz fica em `app/core/permissions.py`, e as rotas declaram a **permissão**, nunca o perfil.

## Observabilidade

- Logs em JSON (`timestamp`, `level`, `logger`, `message`, `request_id` e campos de contexto), sem dados sensíveis.
- Cada resposta devolve `X-Request-ID`, que também aparece nos logs e no corpo dos erros.
- `GET /health` (liveness) e `GET /health/ready` (testa o banco), usados pelos healthchecks do compose.
- Timeouts explícitos:
  - HTTP: 3 s;
  - conexão com o banco: 5 s;
  - `statement_timeout` de 15 s no servidor;
  - pool com `pool_timeout` e `pool_pre_ping`.

---

# Parte 2 — Central de Operações

## Fluxo em tempo real

```mermaid
sequenceDiagram
    participant Sim as simulator (gateway IoT)
    participant API as API (FastAPI)
    participant DB as PostgreSQL
    participant Broker as Broker (LISTEN)
    participant Web as Central (React)

    Sim->>API: POST /telemetry/equipment (X-Gateway-Key) — heartbeat + falha "sem imagem"
    API->>DB: last_seen_at, telemetria amostrada
    API->>DB: situação → mau_funcionamento, OS corretiva, alerta crítico (mesma transação)
    API->>DB: pg_notify(fogo_events, ...) — entregue só no COMMIT
    DB-->>Broker: NOTIFY
    Broker-->>Web: SSE event: alert.opened / equipment.status_changed
    Web->>API: invalida e recarrega só as consultas afetadas (debounce 0,8 s)
    Sim->>API: POST /telemetry/agents (GPS)
    API-->>Web: SSE agents.positions — marcadores andam suavemente
```

- **Transacional**: se o caso de uso falhar, o NOTIFY não é entregue, então não há evento "fantasma" no painel.
- **Fan-out**: uma conexão `LISTEN` dedicada por processo da API, com uma fila limitada por cliente. Um cliente lento recebe `resync` e recarrega o snapshot, sem derrubar ninguém.
- **Front**:
  - posições de agentes vão direto ao cache (sem nova requisição);
  - os demais eventos invalidam só as consultas afetadas (`staleQueriesFor`, testado);
  - o SSE reconecta com backoff e pausa com a aba oculta.

## Alertas

```mermaid
stateDiagram-v2
    [*] --> aberto : regra dispara (falha, furto, offline, vencida, região, bateria)
    aberto --> aberto : repetição (ocorrências +1, criticidade só sobe)
    aberto --> reconhecido : operador assume / despacho
    aberto --> resolvido : causa desaparece (automático) ou operador com nota
    reconhecido --> resolvido
```

| Tipo | Origem | Criticidade |
|---|---|---|
| Falha de equipamento | mudança para *mau funcionamento* (manual ou autodetectada pelo dispositivo) | por tipo (semáforo = crítica), +1 no Centro |
| Furto | mudança para *furtado* | crítica para viatura, moto e câmera; senão alta |
| Sem comunicação | job: sem heartbeat há mais de 5 min (só de quem deveria transmitir) | um nível abaixo da falha |
| Manutenção vencida | job: próxima data já passou | média (equipamento crítico) ou baixa |
| Região degradada | job: índice de saúde abaixo de 85 | alta (crítico) ou média (atenção), acompanha o estado |
| Bateria baixa | telemetria abaixo de 15% (histerese até 25%) | baixa |

SLA: crítica 1 h · alta 4 h · média 24 h · baixa 72 h. `sla_breached` é calculado na leitura.

## Índice de saúde da região

```
nota = 100 × disponibilidade
     − min(40, Σ peso(alertas sem dono) + 0,25 × Σ peso(alertas reconhecidos))   peso: crítica 8, alta 4, média 1,5, baixa 0,5
     − 30 × fração offline − 20 × fração com reparo imediato
nível: ≥ 85 normal · ≥ 70 atenção · < 70 crítico   (+ lista de motivos legíveis)
```

## Despacho inteligente

1. **Elegibilidade**: furto → GCM/PM; equipamento de trânsito → agente de trânsito ou GCM; demais → GCM, trânsito ou PM. Só entra quem está em turno e livre.
2. **Busca**: KNN `ORDER BY coalesce(posição_gps, base) <-> alvo` no PostGIS, com distância em metros (`ST_Distance` em `geography`).
3. **Ranking por ETA**: distância × 1,3 ÷ velocidade (viatura 35, moto 40, a pé 5 km/h).
4. **Despachar** cria o despacho (no máximo um ativo por agente, garantido por índice único parcial), muda o agente para *em ocorrência* com histórico e reconhece o alerta.
5. O **GPS** move a equipe. O backend detecta a saída (mais de 25 m da origem) e a chegada (geofence de 60 m), e o operador conclui o atendimento.

## Simulador (só dispositivos e GPS)

- **Equipamentos**:
  - heartbeat a cada ~30 s com sinal, temperatura (ciclo diário) e bateria (patinetes e veículos autônomos);
  - quedas de conectividade mais frequentes à noite e nas regiões de maior risco;
  - uma falha autodetectada a cada ~3 min, ponderada por tipo e região.
- **Agentes**: em patrulha fazem passeio aleatório dentro da cidade; despachados seguem até o alvo; fora de turno ficam na base.
- **Não toma decisões humanas** (reparos, despachos): essas ficam com o operador. A operação autônoma do PROMETHEUS fica para a Parte 3.


# Parte 3 — Cidade Preditiva e PROMETHEUS

## Visão geral

```mermaid
flowchart LR
    H[(Histórico de situações<br/>calendário de eventos)] --> FIT[model_fit<br/>diário + ao subir]
    FIT --> M[(prediction_models<br/>fatores + backtest + calibração)]
    M --> REF[prediction_refresh<br/>a cada 5 min]
    REF --> S[(prediction_snapshots)]
    T[(Telemetria ao vivo)] --> AN[anomaly_scan<br/>a cada 1 min]
    AN --> S
    AN --> AL[Alertas preventivos]
    S --> SIT[PROMETHEUS: situações]
    SIT --> G{{Grafo LangGraph}}
    KB[(Base de conhecimento<br/>pgvector + BM25)] --> G
    LLM[[Modelo de IA do usuário<br/>opcional]] -.-> G
    G -->|score ≥ limiar| ACT[Ações: OS, alerta,<br/>despacho, reforço]
    G -->|senão| HITL[Pedido de aprovação<br/>interrupt]
    HITL -->|aprovar/rejeitar| G
    ACT --> SIM[Simulador: falha evitada?]
```

## Motor preditivo (`app/domain/prediction/`, puro + numpy)

| Módulo | O que prevê | Método |
|---|---|---|
| `risk_model.py` | ocorrências por região × hora (7 dias) | Poisson multiplicativo, *raking* (IPF), encolhimento empirical Bayes, exposição em equipamento-dias operacionais |
| `backtest.py` | quão bom é o modelo | treino sem as últimas 8 semanas; desvio de Poisson e MAE contra média histórica e perfil por hora; cobertura top-20%; calibração isotônica simples |
| `equipment_risk.py` | chance de falha em 72 h por equipamento | taxa do tipo × tendência × região × preventiva vencida × perfil das próximas 72 h |
| `anomaly.py` | falha iminente e picos regionais | z robusto (mediana/MAD) por equipamento; teste binomial exato de participação regional |
| `reinforcement.py` | efetivo por região e faixa | proporcional ao risco, piso de 8%, mínimo por público de eventos |
| `trends.py` | tendência de disponibilidade | Theil–Sen + projeção do cruzamento de 90% |
| `precursor_model.py` | se um aviso de falha iminente é falha real | regressão logística (IRLS + L2) retreinada a cada desfecho; avaliação temporal (AUC, Brier, precisão × regra) |

O seed e o simulador geram os dados com padrões documentados (`app/seed/city_patterns.py`). Um teste garante que o motor preditivo não importa esses parâmetros: ele aprende só do histórico.

## PROMETHEUS (`app/agent/`)

```mermaid
stateDiagram-v2
    [*] --> retrieve
    retrieve --> plan
    plan --> validate: ação autorizada
    plan --> reject: nenhum procedimento autoriza
    validate --> score
    score --> execute: modo autônomo e score ≥ limiar e risco permitido e teto ok
    score --> request_approval: caso contrário
    request_approval --> await_approval
    await_approval --> execute: aprovado (Command resume)
    await_approval --> reject: rejeitado
    execute --> [*]
    reject --> [*]
```

- **Situações:** `situations.py` transforma retratos e anomalias em situações com `confidence` medida.
- **Checkpointer:** `AsyncPostgresSaver`. O scheduler roda os ciclos; a API retoma o grafo pausado.
- **Ferramentas:** `actions.py`, sempre por meio dos serviços existentes, com o usuário de sistema PROMETHEUS.
- **Chat:** `chat.py`, um agente ReAct (`create_react_agent`) com ferramentas **só de leitura**. A resposta sai em streaming por SSE.

## Base de conhecimento (RAG híbrido)

1. **Ingestão:** arquivos `backend/knowledge/*.md` no bootstrap ou documentos criados na tela. A ingestão é idempotente pelo hash do conteúdo.
2. **Trechos:** um por título, cada um com:
   - lexemas em português, para o BM25;
   - vetor local de 384 dimensões;
   - vetor do provedor (768 dimensões), se configurado.
3. **Busca:** BM25 + cosseno (pgvector HNSW), fundidos por RRF (k = 60).
4. **Autorização:** só trechos de procedimentos com evidência ≥ 0,25 (e tipo e região compatíveis) autorizam ações.

## Modelo de IA do usuário (`app/ai/`)

- **Gateway** (`gateway.py`): o único ponto que chama o LLM. Ele cuida de:
  - configuração e limites diários;
  - disjuntor;
  - saída estruturada (Pydantic);
  - registro de tokens e custo em `ai_usage`.
- **Provedores** (`providers.py`): `ChatOpenAI`, `ChatAnthropic` e `ChatGoogleGenerativeAI`, além do modo compatível com OpenAI por `base_url`. Os erros são traduzidos em mensagens acionáveis.
- **Chave** (`crypto.py`): Fernet com `AI_ENCRYPTION_KEY`; só de escrita.


## Guardrails (`app/domain/guardrails.py`)

Injeção de prompt, segredos e dados pessoais são verificados nos documentos (recusa, com o que foi encontrado) e no chat (mascaramento de dados pessoais, recusa de injeção, limite de perguntas). Documentos da tela autorizam no máximo ações de risco médio. Detalhes na ADR-026.
