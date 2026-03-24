# 📊 Rastreamento de Losses — Guia de Integração

## O Que Foi Implementado

O `FastPatternMiner40s` agora rastreia **automaticamente**:
- ✅ **Total de losses**: quantidade acumulada
- ✅ **Maior sequência de losses**: pior streak consecutivo
- ✅ **Sequência atual de losses**: losses seguidos no momento
- ✅ **Histórico de sequências**: registro de todas as séries de losses finalizadas

---

## Como Usar

### 1. Registrar Losses e Wins

**Quando um padrão dá LOSS:**
```python
bot.miner_40s.registrar_loss()
```

**Quando um padrão dá WIN:**
```python
bot.miner_40s.registrar_win()
```

### 2. Obter Estatísticas Manualmente

```python
stats = bot.miner_40s.obter_stats_losses()

# Retorna:
# {
#   "total_losses": 10,           # Total acumulado
#   "max_loss_sequence": 5,       # Pior sequência
#   "loss_sequence_atual": 2,     # Em andamento agora
#   "historico": [...]            # Últimas 5 sequências
# }

print(f"Total losses: {stats['total_losses']}")
print(f"Maior sequência: {stats['max_loss_sequence']}")
print(f"Sequência atual: {stats['loss_sequence_atual']}")
```

### 3. Automaticamente no Sinal

Toda vez que você gera um sinal, os dados de losses já vêm inclusos:

```python
sinal = bot.miner_40s.gerar_sinal()

if sinal:
    print(f"Sinal: {sinal['sinal']}")
    print(f"Ciclo: {sinal['ciclo']}")
    print(f"Losses: {sinal['losses']}")
    
    # Saída:
    # Losses: {
    #   'total': 10,
    #   'max_sequence': 5,
    #   'atual': 2
    # }
```

---

## Estrutura dos Dados

### Atributos da Instância

```python
miner_40s.total_losses           # int — total acumulado
miner_40s.max_loss_sequence      # int — maior sequência histórica
miner_40s.loss_sequence_atual    # int — sequência em andamento
miner_40s.historico_losses       # list — histórico de sequências finalizadas
```

### Formato do Histórico

```python
[
    {
        "tamanho": 3,              # Quantos losses naquela sequência
        "timestamp": "14:32:45"    # Quando terminou
    },
    {
        "tamanho": 5,
        "timestamp": "14:45:20"
    },
    ...
]
```

### Campo "losses" no Sinal

```python
sinal = {
    "sinal": "V",
    "padroes": [...],
    "ciclo": 42,
    "timestamp": "14:32:45",
    "agregado": "V",
    "losses": {
        "total": 10,              # Total de losses acumulado
        "max_sequence": 5,        # Pior sequência (5 losses seguidos)
        "atual": 2                # Agora estamos em 2 losses
    }
}
```

---

## Exemplo de Integração Completa

### No Loop de Sinais do Bot:

```python
# Quando recebe resultado de um padrão anterior
if resultado == "WIN":
    bot.miner_40s.registrar_win()
    log.info("✅ WIN — sequência resetada")
elif resultado == "LOSS":
    bot.miner_40s.registrar_loss()
    log.info(f"❌ LOSS — sequência atual: {bot.miner_40s.loss_sequence_atual}")

# Quando gera novo sinal
sinal = bot.miner_40s.gerar_sinal()

if sinal:
    # Montar mensagem com losses
    emoji_cor = {"V": "🔴", "P": "⚫"}
    cor_emoji = emoji_cor.get(sinal["sinal"], "?")
    
    msg = (
        f"🎯 <b>Sinal {sinal['ciclo']}</b>\n"
        f"─────────────────────────────\n"
        f"<b>Predição: {cor_emoji}</b>\n"
        f"Padrões: {len(sinal['padroes'])}\n"
        f"Agregado: {emoji_cor.get(sinal['agregado'], '?')}\n"
        f"\n"
        f"📊 <b>Losses</b>\n"
        f"  Total: {sinal['losses']['total']}\n"
        f"  Max Seq: {sinal['losses']['max_sequence']}\n"
        f"  Atual: {sinal['losses']['atual']}\n"
        f"─────────────────────────────\n"
        f"🕐 {sinal['timestamp']}"
    )
    
    # Enviar para Telegram
    await bot._send_async(msg)
```

---

## Casos de Uso

### 1. **Alertar Quando Atingir Limite**

```python
if bot.miner_40s.loss_sequence_atual >= 3:
    await bot._send_async(
        "⚠️ <b>ALERTA: 3 losses consecutivos!</b>\n"
        "Considere pausar ou revisar padrões."
    )
```

### 2. **Exibir Relatório de Losses**

```python
stats = bot.miner_40s.obter_stats_losses()

relatorio = (
    f"📊 <b>Relatório de Losses</b>\n"
    f"───────────────────────\n"
    f"Total: {stats['total_losses']}\n"
    f"Maior sequência: {stats['max_loss_sequence']}\n"
    f"Atual: {stats['loss_sequence_atual']}\n"
    f"───────────────────────\n"
    f"Histórico das 5 últimas:\n"
)

for seq in stats['historico']:
    relatorio += f"  • {seq['tamanho']} losses ({seq['timestamp']})\n"

await bot._send_async(relatorio)
```

### 3. **Filtrar Sinais por Histórico de Losses**

```python
sinal = bot.miner_40s.gerar_sinal()

if sinal:
    # Só enviar sinal se não estamos em streak muito ruim
    if sinal['losses']['atual'] >= 5:
        log.warning(f"Sinal descartado — muito ruim streak: {sinal['losses']['atual']}")
        return
    
    # Enviar sinal
    await enviar_sinal(sinal)
```

---

## Métodos Disponíveis

### `registrar_loss()`
```python
def registrar_loss(self) -> None:
    """Registra um loss e atualiza sequências."""
```

**Uso:**
```python
bot.miner_40s.registrar_loss()
```

---

### `registrar_win()`
```python
def registrar_win(self) -> None:
    """Registra um win e reseta sequência atual."""
```

**Uso:**
```python
bot.miner_40s.registrar_win()
```

---

### `obter_stats_losses()`
```python
def obter_stats_losses(self) -> Dict:
    """Retorna estatísticas atuais de losses."""
```

**Retorna:**
```python
{
    "total_losses": int,
    "max_loss_sequence": int,
    "loss_sequence_atual": int,
    "historico": [...]
}
```

---

### `gerar_sinal()`
```python
def gerar_sinal(self) -> Dict:
    """Gera sinal com losses inclusos (se pode gerar)."""
```

**Retorna:**
```python
{
    "sinal": "V" ou "P",
    "padroes": [...],
    "ciclo": int,
    "timestamp": str,
    "agregado": "V" ou "P",
    "losses": {
        "total": int,
        "max_sequence": int,
        "atual": int
    }
} ou None
```

---

## Fluxo de Exemplo

```
Tempo 0:
  • Gera sinal V → sinal['losses'] = {total: 0, max_seq: 0, atual: 0}

Tempo 5:
  • Resultado: LOSS
  • registrar_loss() → losses = {total: 1, max_seq: 1, atual: 1}

Tempo 10:
  • Resultado: LOSS
  • registrar_loss() → losses = {total: 2, max_seq: 2, atual: 2}

Tempo 15:
  • Resultado: LOSS
  • registrar_loss() → losses = {total: 3, max_seq: 3, atual: 3}

Tempo 20:
  • Resultado: WIN
  • registrar_win() → losses = {total: 3, max_seq: 3, atual: 0}
  • Histórico: [{tamanho: 3, timestamp: "20:00"}]

Tempo 40:
  • Gera novo sinal P → sinal['losses'] = {total: 3, max_seq: 3, atual: 0}

Tempo 50:
  • Resultado: LOSS
  • registrar_loss() → losses = {total: 4, max_seq: 3, atual: 1}

Tempo 60:
  • Resultado: LOSS
  • registrar_loss() → losses = {total: 5, max_seq: 3, atual: 2}

Tempo 70:
  • Resultado: LOSS
  • registrar_loss() → losses = {total: 6, max_seq: 3, atual: 3}

Tempo 80:
  • Gera novo sinal V → sinal['losses'] = {total: 6, max_seq: 3, atual: 3}
```

---

## Testes

Todos os 3 novos testes passaram ✅:

- **Teste 5**: Rastreamento de losses (registrar, sequências, máximos)
- **Teste 6**: Sinal inclui estatísticas de losses
- **Teste 7**: Controle de frequência (40s)

---

## Próximas Ideias Opcionais

1. **Reset automático diário**: Zerar contadores toda manhã
2. **Limiar de alerta**: Alertar via Telegram quando atinge limite
3. **Penalidade de score**: Reduzir confiança de padrões que tiveram muitos losses
4. **Dashboard**: Visualizar histórico de losses em gráfico

---

**Versão**: 1.1.0 | **Status**: ✅ Testado e Pronto | **Data**: 2026-03-23
