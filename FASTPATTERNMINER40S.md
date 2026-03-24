# 🚀 FastPatternMiner40s — Especificação Implementada

## Visão Geral

O **FastPatternMiner40s** é um minerador de padrões **extremamente dinâmico** que recalcula a base de conhecimento do **zero** a cada **40 segundos**, mantendo apenas os padrões que atendem aos critérios rigorosos.

---

## Funcionalidades Principais

### 1. **Recalculação a Cada 40 Segundos**
```
Timer: 40s (não baseado em número de rodadas)
Ciclo: Apaga memória anterior → mineração nova → atualiza padrões
```

### 2. **Análise de Últimas 300 Rodadas**
- **Janela deslizante** = últimas 300 rodadas VP (ignora brancos)
- Quando novas rodadas chegam, remove as mais antigas
- Adaptabilidade máxima ao mercado em tempo real

### 3. **Filtragem Rigorosa**
- **WR Mínimo**: 78% (0.78)
- **Ocorrências Mínimas**: 6
- **Tamanhos de Padrão**: 5 ou 6 cores (ex: `VPVPV` → `V`)

### 4. **Manutenção de Top 40**
- Apenas os **40 melhores** padrões são mantidos
- Ordenação: `WR descendente` (com tie-breaker = volume total)
- Padrões fora do top **desaparecem** naquele ciclo
- Podem "ressurgir" em ciclos futuros se voltarem aos critérios

### 5. **Sinal Agregado**
- Calcula **cor dominante** nas predições dos 40 padrões
- Se `≥50%` predizem `V` → sinal = `🔴 (V)`
- Se `≥50%` predizem `P` → sinal = `⚫ (P)`
- Empatado → prefere `V` por padrão

### 6. **Logging e Resumo**
- Log estruturado a cada ciclo (stdout)
- Resumo formatado para **Telegram** com:
  - Número do ciclo
  - Contagem de padrões ativos
  - Sinal agregado
  - Top 3 padrões com WR e estatísticas
  - Timestamp da mineração

---

## Integração no BlazeBot

### Arquivos Modificados
1. **`bot22.py`**
   - `from fast_pattern_miner_40s import FastPatternMiner40s`
   - `self.miner_40s: Optional[FastPatternMiner40s] = FastPatternMiner40s()` (no `__init__`)
   - `await self.miner_40s.iniciar(lambda: self.history_buffer)` (no `run()`)
   - `await self.miner_40s.parar()` (no `close()`)

2. **`fast_pattern_miner_40s.py`** (novo)
   - Classe `FastPatternMiner40s`
   - Classe `PatternInfo` (dataclass para metadados do padrão)
   - Métodos assíncronos para ciclo contínuo

3. **`test_miner_40s.py`** (novo)
   - 4 testes integrados
   - Validação de lógica, filtros, sinais, formatação

---

## Operação

### Inicialização (Automática ao rodar o bot)
```python
# No __init__ de BlazeBot:
self.miner_40s = FastPatternMiner40s()

# No run():
await self.miner_40s.iniciar(lambda: self.history_buffer)
# Inicia task asyncio que roda infinitamente a cada 40s
```

### Cada Ciclo (a cada 40s)
```
1. Coleta últimas 300 rodadas VP do history_buffer
2. Extrai TODAS as sequências de 5 e 6 cores
3. Calcula WR e ocorrências de cada sequência
4. Filtra: WR >= 78% E ocorrências >= 6
5. Ordena por score (WR desc, volume desc)
6. Mantém TOP 40 apenas
7. Calcula sinal agregado
8. Log e telegram (se novo)
9. Aguarda 40s → próximo ciclo
```

### Acesso aos Dados
```python
# Padrões ativos
bot.miner_40s.padroes_ativos  # Lista de PatternInfo

# Sinal atual
bot.miner_40s.sinal_agregado  # "V" ou "P" ou None

# Resumo formatado
resumo = bot.miner_40s.resumo_ciclo()  # String em HTML para Telegram

# Dados exportáveis
dados = bot.miner_40s.get_top_patterns()  # Lista de dicts
```

### Parada (Graceful Shutdown)
```python
# No close() de BlazeBot:
await self.miner_40s.parar()
# Task asyncio é cancelada corretamente
```

---

## Exemplos de Saída

### Log no Terminal
```
⏱️  Ciclo 42 | 37 padrões | Top WR=89.3% | Agregado=V | 14:32:45
```

### Resumo Telegram
```
⏱️  FastMiner40s — Ciclo 42
─────────────────────────────
📊 37 padrões ativos (top 40)
🎯 Sinal agregado: 🔴 (V)
🕐 14:32:45
─────────────────────────────
TOP 3:
  1. 🔴⚫🔴⚫🔴 → 🔴  WR=89.3% (25W/3L)
  2. ⚫🔴⚫🔴⚫ → 🔴  WR=87.5% (21W/3L)
  3. 🔴🔴🔴⚫🔴 → 🔴  WR=85.0% (17W/3L)

WR mín=78% | Oc mín=6 | Janela=300 rodadas | Recalcula a cada 40s
```

---

## Testes

### Executar Testes
```bash
python test_miner_40s.py
```

### Testes Inclusos
1. **Instanciação Básica** — verifica atributos de configuração
2. **Mineração em Ciclo** — dados sintéticos + validação de filtros
3. **Sinal Agregado** — cálculo de maioria + empatado
4. **Formatação de Resumo** — Telegram HTML válido

### Resultado
```
✅ TODOS OS TESTES PASSARAM!
O FastPatternMiner40s está pronto para integração.
```

---

## Comparação: Minerador Antigo vs. Novo

| Aspecto | `_minerar_tempo_real()` | `FastPatternMiner40s` |
|---------|-------------------------|----------------------|
| **Frequência** | A cada 5 rodadas | A cada 40 segundos |
| **Lógica** | Incrementalmente (adiciona padrões) | Do zero (recalcula tudo) |
| **Memória** | Padrões persistem entre ciclos | Descarta todos fora do top 40 |
| **Dinâmica** | Moderada | Extrema (40s = ~2-3 rodadas) |
| **Utilidade** | Descoberta contínua | Adaptação ao mercado |

---

## Detalhes Técnicos

### Classe `PatternInfo`
```python
@dataclass
class PatternInfo:
    pattern: Tuple          # (V, P, V, P, V)
    prediction: str         # "V" ou "P"
    winrate: float          # 0.78 a 1.00
    wins: int              # Número de vitórias
    total: int             # Total de ocorrências
```

### Classe `FastPatternMiner40s`
- **Atributos principais**:
  - `padroes_ativos`: Lista atual de top 40
  - `sinal_agregado`: Cor dominante
  - `ciclos_rodados`: Contador de ciclos
  - `ultima_atualizacao`: Timestamp do último ciclo

- **Métodos públicos**:
  - `iniciar(get_history_buffer)`: Inicia task asyncio
  - `parar()`: Cancela task asyncio
  - `get_top_patterns()`: Exporta como dicts
  - `resumo_ciclo()`: Retorna string formatada

- **Métodos privados**:
  - `_loop_mineracao_continua()`: Loop asyncio
  - `_minerar_ciclo()`: Lógica de filtragem
  - `_calcular_sinal_agregado()`: Cor dominante

---

## Compatibilidade

- ✅ Python 3.8+
- ✅ Asyncio (nativo)
- ✅ Sem dependências externas
- ✅ Graceful shutdown
- ✅ Thread-safe (asyncio nativo)

---

## Próximos Passos Opcionais

1. **Persistência**: Salvar top 40 em arquivo JSON a cada ciclo
2. **Métricas**: Histograma de WR, tempo médio de ciclo
3. **Dashboard**: WebSocket para visualizar em tempo real
4. **Customização**: Parâmetros (ciclo, janela, filtros) via config.ini

---

## Histórico de Commits

- **Commit**: `feat: FastPatternMiner40s - minerador dinâmico recalculado a cada 40s`
  - Novo módulo + testes + integração
  - ✅ Todos os critérios implementados
  - ✅ Testes passando
  - ✅ Push para GitHub completo

---

**Versão**: 1.0.0 | **Data**: 2026-03-23 | **Status**: ✅ Pronto para Produção
