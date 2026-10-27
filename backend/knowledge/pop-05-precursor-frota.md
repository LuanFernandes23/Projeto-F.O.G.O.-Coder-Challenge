---
titulo: "POP-05 — Frota conectada com sinais de falha (veículos, viaturas e patinetes)"
tipo: procedimento
situacoes: [precursor_falha, risco_equipamento]
tipos_equipamento: [veiculo_transporte, veiculo_fiscalizacao_autonomo, viatura, moto_agente, patinete]
acoes_permitidas: [abrir_os_preventiva, alerta_preventivo]
acao_padrao: abrir_os_preventiva
autonomia_max: baixo
---

# POP-05 — Frota conectada com sinais de falha (veículos, viaturas e patinetes)

> Procedimento operacional padrão fictício, criado para a demonstração do F.O.G.O.

## Sinais típicos
- Veículo de transporte e de fiscalização autônoma: queda de disponibilidade do link de telemetria e aquecimento do módulo embarcado antes de perder a comunicação.
- Viatura e moto de agente: perda de sinal do rastreador antes de a unidade sumir do mapa.
- Patinete elétrico: aquecimento da bateria e queda de link antes de travar.

## Ação imediata (pode ser automática)
Abrir **ordem de manutenção preventiva imediata** para a oficina ou a equipe técnica da frota. A equipe reinicia o módulo de telemetria ou recolhe o veículo no próximo ponto de parada. Não é necessário deslocar agentes: o risco à população é baixo.

## Observações
- Viatura ou moto em atendimento não é recolhida no meio da ocorrência: a ordem fica aberta e o recolhimento acontece ao fim do atendimento.
- Veículo de transporte com passageiros conclui a viagem antes do recolhimento.
- Se o veículo já tiver ordem aberta, apenas registrar a nova evidência na ordem existente.
