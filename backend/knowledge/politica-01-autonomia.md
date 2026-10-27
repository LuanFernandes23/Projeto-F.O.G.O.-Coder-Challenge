---
titulo: "Política de autonomia do PROMETHEUS"
tipo: politica
situacoes: [precursor_falha, risco_equipamento, pico_regional, deficit_efetivo]
acoes_permitidas: [abrir_os_preventiva, alerta_preventivo, despachar_inspecao, reforcar_regiao]
autonomia_max: medio
---

# Política de autonomia do PROMETHEUS

> Documento fictício, criado para a demonstração do F.O.G.O.

## Princípio
O PROMETHEUS age sozinho **apenas** quando três condições se cumprem:

1. A **confiança estatística** da previsão (calibrada no backtest) é alta.
2. Existe um **procedimento na base de conhecimento** que autoriza a ação para aquela situação.
3. A ação é de **risco baixo ou médio** e está dentro do limite de execuções por hora.

Nos demais casos, o PROMETHEUS **pede aprovação humana**, mostrando a evidência, o score e o procedimento consultado.

## Classes de risco das ações
- **Baixo**: abrir ordem preventiva, emitir alerta preventivo. Reversíveis e sem deslocamento de pessoas.
- **Médio**: despachar agente para inspeção preventiva. Desloca uma pessoa, mas é reversível.
- **Alto**: remanejar efetivo entre regiões. **Sempre** exige aprovação do gestor.

## Freios
- Modo de operação: autônomo, só sugestão ou pausado (definido pela gestão).
- Teto de execuções automáticas por hora, por tipo de ação.
- Pedidos de aprovação expiram em 30 minutos.
- Toda decisão fica registrada com o "porquê": dados, score, procedimento e quem aprovou.
