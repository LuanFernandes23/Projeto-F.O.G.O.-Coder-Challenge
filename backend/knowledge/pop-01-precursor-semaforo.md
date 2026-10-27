---
titulo: "POP-01 — Semáforo com sinais de falha iminente"
tipo: procedimento
situacoes: [precursor_falha, risco_equipamento]
tipos_equipamento: [semaforo]
acoes_permitidas: [abrir_os_preventiva, despachar_inspecao, alerta_preventivo]
acao_padrao: abrir_os_preventiva
autonomia_max: medio
---

# POP-01 — Semáforo com sinais de falha iminente

> Procedimento operacional padrão fictício, criado para a demonstração do F.O.G.O.

## Quando aplicar
Quando a telemetria do controlador semafórico mostrar, ao mesmo tempo, **temperatura acima do normal**, **queda de sinal** ou **queda de disponibilidade do link**. Esse padrão costuma anteceder em 5 a 15 minutos o apagão do grupo focal ou o modo amarelo intermitente.

## Ação imediata (pode ser automática)
1. Abrir **ordem de manutenção preventiva com prioridade imediata**. A concessionária de semáforos reinicia o controlador remotamente ou troca a fonte em campo; o tempo de resposta contratado é de até 5 minutos para acionamento remoto.
2. Registrar no alerta os valores medidos e o horário da detecção.

## Ação complementar (pede validação humana)
Em **horário de pico** (7h–9h e 17h–19h, dias úteis) ou na **região Centro**, despachar um agente de trânsito para o cruzamento enquanto a concessionária atua. A presença do agente evita colisões se o semáforo apagar.

## Por que agir antes
Semáforo apagado em cruzamento movimentado é ocorrência de criticidade máxima. Uma intervenção preventiva custa, em média, um sexto de um atendimento corretivo com interdição.
