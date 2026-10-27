# Registro de decisões arquiteturais (ADRs)

Cada decisão segue o formato **contexto → decisão → consequências**.

---

## ADR-001 — Camada de domínio e Data Mapper

**Contexto.** O padrão interno prefere Data Mapper, que separa a estrutura do banco, os objetos de domínio, os contratos e as regras. O layout sugerido não tem uma pasta `domain/`.

**Decisão.** Foi criada a camada `app/domain` com dataclasses e regras puras. Os modelos SQLAlchemy (`database/models`) nunca saem dos repositórios: eles convertem linha ↔ domínio. Os serviços dependem de **protocolos** (`services/ports.py`), e não das classes SQLAlchemy.

**Consequências.**
- As regras centrais (máquina de estados, manutenção, agentes) são testadas sem banco, em cerca de 1 s.
- O mapeamento é um pouco mais verboso, mas trocar a persistência ou otimizar consultas com SQL direto não afeta os serviços.
- `tests/` fica fora de `app/` para não ir na imagem de produção.

## ADR-002 — Características por tipo: JSONB + schema Pydantic (híbrido)

**Contexto.** Cada tipo de equipamento tem propriedades próprias, e o enunciado diz "entre outros", ou seja, os tipos são abertos.

**Decisão.** Os tipos ficam na tabela `equipment_types`. As características ficam em `attributes JSONB`, validadas por um schema Pydantic estrito (`extra="forbid"`) para cada tipo conhecido. Novos tipos criados pela API usam o schema `outro`, com atributos livres de valores simples.

**Alternativas.**
- Tabela por tipo: cada tipo novo exigiria migration.
- JSON Schema dinâmico no banco: validação e documentação genéricas.

**Consequências.**
- A validação é forte, com mensagens por campo, e o JSON Schema exposto deixa o front gerar formulários dinâmicos.
- O índice GIN em `attributes` permite filtros futuros por característica.
- Um tipo novo só ganha validação tipada quando seu schema é escrito no código.

## ADR-003 — PostGIS para localização

**Contexto.** As Partes 2 e 3 vão precisar de mapa, raio, agente mais próximo, agrupamento por região e mapas de calor.

**Decisão.** A localização é `geography(Point, 4326)` com índice GIST, e as regiões são `MultiPolygon`. A região é atribuída automaticamente com `ST_Covers`, e a busca por raio usa `ST_DWithin` com ordenação por `ST_Distance`.

**Consequências.**
- Consultas espaciais corretas (em metros) e indexadas desde já.
- Imagem do banco um pouco maior (`postgis/postgis`).

## ADR-004 — Máquina de estados explícita + histórico append-only

**Decisão.** As transições permitidas ficam em uma tabela de código (`domain/equipment/status.py`). A situação só muda por um endpoint de comando (`status-changes`), que grava `equipment_status_history` com origem, destino, motivo, autor e data. O `PATCH` não altera a situação.

**Consequências.**
- Não existe "furtado → operacional" sem recuperação e reinstalação.
- A trilha de auditoria completa vira a matéria-prima da Parte 3: disponibilidade, MTBF e tempo de reparo por região e tipo.
- O front consulta `GET /equipment-statuses` para mostrar só as ações válidas.

## ADR-005 — Retrato de manutenção desnormalizado

**Contexto.** Filtrar "manutenção imediata" ou "vence em até N dias" em listas paginadas exige que o critério esteja no banco.

**Decisão.** `equipment.maintenance_need` e `equipment.next_maintenance_date` são recalculados pela política de domínio **na mesma transação** de qualquer evento relevante: plano, ordem, situação ou job. Os indicadores `is_overdue` e `is_due_soon` dependem da data de hoje e são calculados na leitura.

**Consequências.**
- Filtro e ordenação usam índice.
- Existe uma única fonte de verdade (`compute_maintenance_need`).
- Toda escrita precisa passar pelos serviços, e o próprio seed obedece a isso (ADR-007).

## ADR-006 — Concorrência e idempotência

**Decisões.**
- **Lock otimista** (`version`) nas edições de equipamento e agente, retornando 409 em caso de conflito.
- `SELECT … FOR UPDATE` em comandos de situação e ordens.
- **Índice único parcial**: no máximo uma ordem aberta por equipamento e tipo de ordem. Isso torna idempotentes a abertura automática por defeito e o job.
- **Advisory lock** do PostgreSQL no job de preventivas, para que várias réplicas do scheduler não dupliquem ordens. Além disso, o APScheduler usa `max_instances=1` e `coalesce`.

## ADR-007 — Seed por simulação

**Contexto.** Dados de demonstração inseridos "na mão" costumam violar as regras: histórico incoerente, ordens órfãs e nenhum padrão para análise.

**Decisão.** O seed usa um relógio controlado (`ManualClock`) e chama os **mesmos serviços da API** para viver um ano de Marília-SP:
- instalações;
- falhas, com taxa por tipo, fator de risco por região e mais ocorrências à noite;
- reparos, alguns aguardando peça;
- preventivas, às vezes atrasadas;
- furtos e turnos de agentes nas escalas 6x1 e 12x36.

A geração é determinística (`random.Random(2026)`), com 8 simulações concorrentes.

**Consequências.**
- Os dados passam por todas as regras.
- O histórico tem padrões reais para a Parte 3.
- A primeira subida leva cerca de 1 minuto.

## ADR-008 — Autenticação JWT + RBAC por permissão

**Decisão.**
- O token JWT de acesso (HS256) carrega só o `sub` e o perfil.
- **Usuário e perfil são relidos do banco a cada requisição**, então desativar ou trocar o perfil vale na hora.
- As rotas exigem permissões, e a matriz perfil → permissões fica em um único arquivo.
- Senhas usam Argon2id. O login verifica um hash descartável quando o e-mail não existe, para manter o tempo de resposta constante.
- O domínio impede remover o último administrador ativo, e um administrador não pode rebaixar nem desativar a si mesmo.

**Fora do escopo agora.** Refresh token e rate limiting do login, que entram junto com o front.

## ADR-009 — Integração de CEP com cadeia de provedores

**Decisão.** `AddressLookupService` recebe uma lista de `CepProvider`: ViaCEP primeiro e BrasilAPI v2 como fallback, que também traz coordenadas quando disponíveis. Detalhes:
- um `httpx.AsyncClient` único, criado no lifespan;
- timeout de 3 s;
- cache TTL/LRU em memória apenas para respostas positivas;
- 404 se nenhum provedor conhece o CEP, 503 se todos falharam.

**Consequências.** A indisponibilidade externa nunca bloqueia o cadastro, que aceita o endereço manual.

## ADR-010 — Versões

As versões fixadas pelo padrão interno (FastAPI 0.136.3, Pydantic 2.13.4, SQLAlchemy 2.0.50, psycopg 3.3.4, httpx 0.28.1, APScheduler 3.11.2) foram mantidas. Os complementos também têm versão exata, e o `requirements.txt` traz o lock completo gerado na imagem Linux.

O `psycopg-pool` não foi incluído: o pool do SQLAlchemy atende ao padrão ("pool do próprio SQLAlchemy ou psycopg-pool") e evita dois pools concorrentes.

---

# Parte 2

## ADR-011 — Tempo real com SSE + PostgreSQL LISTEN/NOTIFY

**Contexto.** O painel só *recebe* eventos. Há vários processos produzindo eventos (API, scheduler), e a infraestrutura deveria continuar simples.

**Decisão.**
- Os serviços publicam eventos com `pg_notify` **na mesma transação** do caso de uso.
- A API mantém uma conexão `LISTEN` e repassa os eventos por **Server-Sent Events**. O front usa `fetch-event-source`, que permite o cabeçalho `Authorization`.

**Alternativas.** WebSocket + Redis seria bidirecional, mas exigiria mais infraestrutura sem ganho. Polling geraria mais tráfego e mais atraso.

**Consequências.**
- Zero serviços novos, com entrega atômica junto com o commit.
- Payloads limitados a 8 KB: posições vão em lotes.
- Para escalar horizontalmente basta mais réplicas da API, já que cada uma tem seu `LISTEN`.

## ADR-012 — Simulador como gateway IoT externo (HTTP + chave)

**Decisão.**
- O simulador é um processo separado que conversa com a API **pelos mesmos endpoints** que um gateway real usaria (`/telemetry/*`, autenticado por `X-Gateway-Key` com comparação em tempo constante).
- Ele simula apenas dispositivos e GPS.

**Consequências.**
- A ingestão é testada de verdade.
- Trocar o simulador por dispositivos reais não muda a API.
- As decisões humanas ficam visíveis no painel, e a automação será tarefa do PROMETHEUS na Parte 3.

## ADR-013 — Motor de alertas idempotente com SLA

**Decisão.**
- Os alertas têm `dedup_key` (tipo:sujeito) com **índice único parcial enquanto não resolvido**.
- `raise_alert` abre ou atualiza (conta ocorrência e só escala a criticidade), e `resolve` fecha quando a causa some.
- As regras puras de criticidade e SLA ficam no domínio.
- Os gatilhos vêm de três fontes: mudança de situação (`EquipmentLifecycle`), telemetria (reconexão, bateria) e um **job de varredura** (offline, vencida, região), com advisory lock.

**Consequências.**
- Nenhum alerta duplicado, mesmo com jobs e requisições concorrentes.
- O feed mostra o estado real, e o histórico de alertas vira insumo para a Parte 3.

## ADR-014 — Índice de saúde por região explicável

**Decisão.** A nota de 0 a 100 é calculada por uma fórmula simples e pública (disponibilidade menos penalidades), acompanhada da **lista de motivos**. Alertas reconhecidos pesam 1/4 (só o risco residual; a falha já desconta na disponibilidade).

**Por quê.** Um gestor precisa confiar e agir: "Zona Sul 64 — disponibilidade 80%, 2 alertas críticos sem tratamento" diz o que fazer. Um score opaco não diria.

## ADR-015 — Front: React + Tailwind/shadcn + Leaflet/OSM

**Decisão.**
- React 18 + TS estrito + Vite, TanStack Query para o estado de servidor, shadcn/ui (Radix) para acessibilidade.
- Leaflet com **tiles oficiais do OpenStreetMap**. No mapa escuro, um filtro CSS age só sobre os tiles, porque o basemap escuro da CARTO passou a exigir chave. O estilo do mapa é independente do tema (ADR-018).
- Os tipos da API são **gerados do OpenAPI**.
- Versões são majors consolidadas, com versões exatas fixadas.

**Detalhes.**
- Os filtros do mapa rodam no cliente sobre um snapshot leve (`/operations/map-features`, ~60 KB): resposta instantânea.
- As listas de inventário paginam no servidor.
- Os ícones do mapa têm cache por "visual" (tipo + situação + destaques).

## ADR-016 — Front servido por nginx na mesma origem

**Decisão.** O nginx serve o SPA e faz proxy de `/api`. O SSE vai com `proxy_buffering off` e timeout longo, e os assets com hash têm cache imutável.

**Consequências.** Sem CORS em produção, cabeçalhos de segurança centralizados e um único endereço para o avaliador (http://localhost:8080).

## ADR-017 — Mapa em tela cheia com barra flutuante de abas

**Contexto.** A primeira versão tinha filtros numa coluna à esquerda e quatro abas numa coluna à direita. O mapa, que é o centro da Central, ficava espremido, e a lateral direita misturava muita informação de uma vez.

**Decisão.**
- Mapa em tela cheia, com só os KPIs no topo. Alertas, Regiões, Equipes, Análises, Filtros e Camadas viram abas de uma **barra flutuante** (`components/ui/motion-dock.tsx`, implementação própria com `motion`).
- Comportamento:
  - a pílula se expande com mola, e o rótulo da aba aparece logo depois;
  - o painel mede o conteúdo (ResizeObserver) e anima a altura;
  - o conteúdo desliza para a esquerda ou para a direita conforme a direção da troca;
  - fecha com Esc ou clique fora.
- A barra é **arrastável** pela alça. A posição fica salva e volta para dentro da área se a janela diminuir; duplo clique centraliza. O painel abre do lado com mais espaço e nunca sai da área do mapa.
- Acessibilidade: `tablist`/`tab`/`tabpanel`, setas, Home e End entre abas, `aria-expanded`, e `MotionConfig reducedMotion="user"`.
- "Mapa" num alerta ou despacho fecha o painel, porque o mapa centraliza o ponto exatamente onde o painel estaria.
- **Cartões com tom semântico** (`components/ui/tone.tsx`): borda esquerda, brilho radial discreto e valor na cor do tom (bom, atenção, ruim, informativo), sem depender só da cor.

**Consequências.**
- O mapa ganha cerca de 40% de área útil, e cada assunto aparece só quando pedido.
- Uma dependência a mais (`motion`, versão exata), carregada só no chunk da Central.

## ADR-018 — Estilo do mapa independente do tema

**Decisão.** O estilo do mapa pode ser automático (segue o tema), claro, escuro ou satélite (Esri World Imagery, com atribuição). A escolha:
- fica num store mínimo com `useSyncExternalStore` e `localStorage` (`features/operations/map/map-style.tsx`);
- vale para o mapa da Central e para o minimapa do cadastro;
- é aplicada por uma classe num invólucro (`fogo-map--escuro` etc.), porque o `MapContainer` congela o `className` na criação.

**Consequências.** O operador escolhe o fundo pela tarefa (satélite para conferir um endereço, escuro para a sala de controle) sem mudar a interface inteira.

## ADR-019 — Previsões estatísticas e explicáveis, com backtest (não um LLM)

**Contexto.** A Parte 3 pede antecipar problemas e deixar claro *o que* se prevê, *com quais dados* e *como ajuda*. Um avaliador provavelmente não terá chave de IA, e a "confiança" que um LLM declara não é calibrada.

**Decisão.**
- **Risco de ocorrências (região × dia × hora):** Poisson multiplicativo ajustado por *raking* (IPF), com fatores com nome: região, hora, tipo de dia × faixa de 4 h, mês e tipo de evento do calendário. Cada fator é encolhido para 1 (empirical Bayes) e a exposição é medida em **equipamento-dias em operação** (quem está em reparo não pode falhar).
- **Backtest:** o modelo é treinado sem as últimas 8 semanas e prevê essas semanas. Ele é comparado com duas linhas de base ingênuas (média histórica e perfil por hora), com desvio de Poisson, cobertura nos 20% mais arriscados e **curva de calibração**.
- **Equipamentos em 72 h:** taxa por tipo (encolhida para o grupo) × tendência recente × região × preventiva vencida × perfil das próximas 72 h. Os efeitos são **medidos** no histórico (ex.: preventiva vencida ×1,6).
- **Anomalias:** escore robusto (mediana/MAD) contra a última hora do próprio equipamento, e teste binomial da participação de cada região (imune ao volume total).
- **Tendência:** Theil–Sen sobre a disponibilidade diária, com projeção da data em que cruza 90%.
- **Reforço de efetivo:** distribuição proporcional ao risco previsto, com piso por região e regra de eventos (1 agente a cada 2.000 pessoas).

**Consequências.**
- Tudo funciona sem chave de IA, roda em segundos e cabe em testes que conferem se o modelo recupera fatores conhecidos.
- O backtest mostrou, com honestidade, que **o horário domina o volume**. Os demais fatores foram redescobertos na direção certa (Norte o mais arriscado, noites de sexta e sábado, shows, preventiva vencida, envelhecimento dos patinetes), mas o ganho marginal sobre o "perfil por hora" fica dentro do ruído de 8 semanas. A tela mostra isso, em vez de esconder.

## ADR-020 — Dados simulados com padrões, sem vazamento para o modelo

**Contexto.** O seed das Partes 1 e 2 só tinha padrão de hora e região, e a telemetria ao vivo era ruído. Sem sinal, qualquer previsão "descobriria" ruído.

**Decisão.**
- O seed passou a usar um **processo de Poisson não homogêneo** (*thinning*), modulado por hora, tipo de dia, estação chuvosa, calendário de eventos, preventiva vencida e envelhecimento dos patinetes. A densidade do histórico também aumentou, para cerca de 1.300 ocorrências por ano.
- O calendário de eventos (feriados, jogos do MAC, shows, feiras) vai para a tabela `city_events`. É informação pública que a prefeitura conhece e, portanto, entrada legítima do modelo.
- Os multiplicadores "verdadeiros" ficam em `app/seed/city_patterns.py`. Um **teste garante** que `app/domain/prediction` nunca importa o seed nem o simulador.
- Simulador:
  - as falhas passam a ter **precursores** (temperatura sobe, sinal e uptime caem 8 a 15 min antes);
  - 25% das falhas são súbitas e 25% dos desvios são **alarmes falsos**;
  - uma intervenção a tempo (OS preventiva imediata ou equipe no local) **evita a falha**, e o simulador informa isso (`fault_averted`).
- O seed também grava a última 1,5 h de telemetria, com uma linha de base estável por equipamento, para a detecção de anomalias funcionar desde o primeiro minuto.

**Consequências.**
- A precisão, a cobertura e a antecedência das detecções são medidas ao vivo, contra um gabarito real.
- "Falhas evitadas" é verdade de campo **só na simulação**. Numa cidade real seria uma estimativa (probabilidade × intervenções), o que fica dito na documentação.

## ADR-021 — PROMETHEUS: LangGraph com humano no circuito e checkpointer Postgres

**Decisão.**
- **Grafo:** `retrieve → plan → validate → score → (execute | request_approval → interrupt → execute/reject)`.
- **Retomada:** o estado é salvo pelo `AsyncPostgresSaver` (pool psycopg próprio). O scheduler roda os ciclos e a **API retoma** com `Command(resume=...)` quando alguém aprova ou rejeita.
- **Efeitos colaterais isolados:** o pedido de aprovação é gravado num nó **anterior** ao `interrupt()`, porque o nó do interrupt é reexecutado na retomada.
- **Ações:** as ferramentas são os serviços já existentes, executados como um **usuário de sistema** (`prometheus@fogo.dev`). Assim, todo o histórico mostra quem agiu.
- **Parâmetros:** vêm da situação (dados), nunca do texto do LLM. O LLM escolhe só **uma ação da lista branca** autorizada pelo procedimento recuperado. Isso também protege contra injeção de prompt vinda da base.
- **Freios:**
  - modo global (autônomo, só sugestão ou pausado);
  - teto de execuções automáticas por hora;
  - expiração dos pedidos de aprovação;
  - deduplicação de situações por janela;
  - trilha completa em `agent_decisions`: dados, citações, plano, score detalhado, quem decidiu e resultado.

**Alternativas descartadas.**
- Arquitetura com RAG e o HITL no projeto.
- Grafo sem checkpointer (não permite pausar e retomar).

## ADR-022 — Autonomia por score composto, decidida pelo código

**Decisão.**
- `score = confiança × evidência`.
  - **Confiança** é uma probabilidade medida: a precisão observada das detecções (prior Beta(3, 1)), 1 − p-valor no pico regional ou a probabilidade do modelo em 72 h.
  - **Evidência** é a similaridade do melhor trecho da base que autoriza a ação.
- O agente age sozinho só se:
  1. o modo for autônomo;
  2. o plano for válido;
  3. o score atingir o limiar da ação;
  4. o procedimento permitir aquele nível de risco;
  5. o teto por hora não tiver sido atingido.
- Cada condição que falha vira um motivo legível no pedido de aprovação.
- **Risco alto** (remanejar efetivo) sempre pede aprovação.
- Os limiares por ação são editáveis na Administração, com valores iniciais na migration.

**Consequência.** A autonomia é auditável e ajustável pela gestão, e não depende do humor do modelo.

## ADR-023 — RAG híbrido: BM25 + embeddings locais (+ do provedor), fusão RRF

**Decisão.**
- **Documentos:** markdown com front matter (situações, ações permitidas, ação padrão, autonomia máxima).
- **Trechos:** divididos por título, cada um com o caminho de títulos como contexto.
- **Busca, em três rankings:**
  - **BM25 real** sobre os radicais em português do PostgreSQL (`to_tsvector('portuguese')`);
  - **vetor local** (`paraphrase-multilingual-MiniLM-L12-v2` via fastembed/ONNX, 384 dimensões, baixado no build da imagem);
  - opcionalmente, o **vetor do provedor** (OpenAI ou Gemini, 768 dimensões) com a mesma chave do chat.
- **Fusão:** os rankings se juntam por **RRF** (k = 60). Cada resultado mostra a posição em cada busca.
- **Índices:** pgvector com HNSW (cosseno). A imagem do Postgres foi estendida com o pacote oficial `postgresql-16-pgvector`.

**Consequências.**
- O RAG semântico funciona sem chave e com qualquer provedor (a Anthropic não tem API de embeddings).
- A imagem da API cresce cerca de 300 MB (o modelo), mas o zip de entrega não.

## ADR-024 — Chave de IA do usuário (BYOK), só de escrita

**Decisão.**
- **Configuração:** uma linha única em `ai_settings`.
- **Chave:** cifrada com **Fernet** (`AI_ENCRYPTION_KEY`). O `GET` devolve só `has_key` e os 4 últimos caracteres, e omitir a chave no `PUT` mantém a atual. Trocar de provedor descarta a chave do anterior.
- **Permissão:** própria (`ai:configure`, só admin).
- **Testar antes de salvar:** uma chamada de cerca de 20 tokens. Listar os modelos não tem custo.
- **Provedores:** OpenAI, Anthropic, Gemini e qualquer servidor compatível com OpenAI (Ollama, OpenRouter, Azure).
- **Proteções:** todas as chamadas passam por um gateway com timeout, retentativas, **disjuntor** (3 falhas de rede pausam a IA por 5 min) e **limites diários** de chamadas e de tokens. O consumo e o custo estimado ficam em `ai_usage`.
- **Sem chave:** o sistema inteiro funciona em modo determinístico. Previsões, busca e decisões seguem normais; só o chat exige IA.


## ADR-025 — Classificador de precursores que aprende com os desfechos

**Contexto.** Perguntamos onde machine learning agregaria de verdade. Trocar o modelo de risco por boosting (XGBoost) seria "mais do mesmo": com cerca de 1.300 eventos por ano, o backtest mostrou que nem os fatores atuais ganham do perfil por hora. Mas os avisos de falha iminente geram **rótulos reais** a cada desfecho (falhou, evitada, alarme falso).

**Decisão.**
- **Modelo:** regressão logística (IRLS com L2, em numpy) sobre os escores robustos de temperatura, sinal e uptime, o número de sinais fortes e o grupo do equipamento.
- **Retreino:** automático sempre que chegam desfechos novos (job `anomaly_scan`), com o modelo versionado em `prediction_models`.
- **Ativação:** só com 30 ou mais rótulos e 5 ou mais de cada classe. Antes disso, vale a precisão observada com prior Beta(3, 1).
- **Avaliação temporal:** 70% mais antigos → 30% mais recentes, com AUC, Brier e precisão contra a regra "todo alarme é falha".
- **Uso:** a probabilidade vira a **confiança** do PROMETHEUS para avisos de falha iminente.
- **Dados para aprender:** o simulador passou a gerar alarmes falsos com padrão próprio e sobreposto (aquecimento sem queda de link), e o seed traz 30 dias de detecções com desfecho.

**Consequências.** O sistema melhora com o uso, de forma mensurável e explicável. Com volume maior, o mesmo encaixe aceitaria um modelo mais flexível sem mudar o resto.

## ADR-026 — Guardrails de conteúdo (base de conhecimento e chat)

**Decisão.** Ficam em `app/domain/guardrails.py`, como regras puras e testadas:
- **Documentos da tela:**
  - recusa injeção de prompt, segredos e dados pessoais;
  - exige estrutura em seções e no máximo 20 mil caracteres;
  - **teto de autonomia médio**;
  - o erro devolve a lista do que foi encontrado, e o editor mostra as verificações.
- **Arquivos do repositório:** mesma varredura no bootstrap.
- **Chat:**
  - mascara dados pessoais e segredos antes do LLM (com aviso visível);
  - recusa injeção;
  - limita o tamanho da pergunta e o número de perguntas por usuário (15 a cada 10 min);
  - prompt restrito ao domínio;
  - ferramentas só de leitura;
  - remove segredos também da saída.
- A revisão por uma segunda pessoa foi considerada e descartada: as verificações automáticas mais o teto de autonomia bastam para o escopo.

**Consequências.** Proteções explícitas e auditáveis, visíveis para o usuário. São baseadas em padrões e, por isso, não pegam tudo. Complementam, e não substituem, a política de autonomia e o RBAC.
