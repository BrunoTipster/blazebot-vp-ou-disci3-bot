# ══════════════════════════════════════════════════════════════════
# FastPatternMiner40s — Minerador de Padrões Recalculado a Cada 40s
# ══════════════════════════════════════════════════════════════════
# 
# Objetivo: Análise extremamente dinâmica
#   • Recalcula DO ZERO a cada 40 segundos
#   • Analisa ÚLTIMAS 300 rodadas (janela deslizante)
#   • Filtro rígido: WR ≥ 78% E ocorrências ≥ 6
#   • Mantém apenas TOP 40 padrões
#   • Padrões fora do top desaparecem naquele ciclo
#   • Emite 1 sinal por ciclo (melhor padrão com previsão agregada)
#

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Tuple
from dataclasses import dataclass, field

log = logging.getLogger("BlazeBotVP")

@dataclass
class PatternInfo:
    """Representa 1 padrão candidato com suas estatísticas"""
    pattern: Tuple  # (V, P, V, P, V) etc
    prediction: str  # "V" ou "P" — cor com mais hits
    winrate: float
    wins: int
    total: int
    
    def score(self) -> float:
        """Score para ranking: WR é primário, total é tie-breaker"""
        return self.winrate * 1000 + (self.total / 1000)

class FastPatternMiner40s:
    """
    Minerador contínuo que roda a cada 40 segundos:
      1. Tira as últimas 300 rodadas do buffer de histórico
      2. Extrai sequências de 5 e 6 cores
      3. Calcula win-rate e ocorrências de cada sequência
      4. Filtra: WR >= 0.78 E ocorrências >= 6
      5. Ordena por WR desc (com tie-breaker de volume)
      6. Mantém apenas TOP 40
      7. Descarta tudo mais (aquele ciclo)
      8. Retorna lista e também um "sinal agregado" (cor dominante no top 40)
    """
    
    CYCLE_SECONDS = 40      # Roda a cada 40s
    JANELA_RODADAS = 300    # Analisa últimas 300 rodadas
    MIN_WINRATE = 0.78      # 78% mínimo
    MIN_OCORRENCIAS = 6     # Ocorrências mínimas
    TOP_KEEP = 40           # Mantém apenas top 40
    TAMANHOS = [5, 6]       # Tamanhos de padrão testados
    
    def __init__(self):
        self.padroes_ativos: List[PatternInfo] = []
        self.ultima_atualizacao = datetime.now().strftime("%H:%M:%S")
        self.ciclos_rodados = 0
        self.sinal_agregado = None  # Cor dominante do último ciclo
        self.task = None
    
    async def iniciar(self, get_history_buffer) -> None:
        """
        Inicia a tarefa de mineração contínua.
        
        Args:
            get_history_buffer: função que retorna self.history_buffer do bot
                                (lista de cores ["V","P","V","B",...])
        """
        self.task = asyncio.create_task(
            self._loop_mineracao_continua(get_history_buffer)
        )
        log.info("🚀 FastPatternMiner40s iniciado | ciclo=40s | janela=300 rodadas")
    
    async def parar(self) -> None:
        """Cancela a tarefa de mineração"""
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            log.info("⛔ FastPatternMiner40s parado")
    
    async def _loop_mineracao_continua(self, get_history_buffer) -> None:
        """Loop infinito: a cada 40s, recalcula padrões do zero"""
        try:
            while True:
                await asyncio.sleep(self.CYCLE_SECONDS)
                
                # Pega histórico atual
                historia = get_history_buffer()
                if not historia:
                    continue
                
                # Recalcula padrões
                novos_padroes = self._minerar_ciclo(historia)
                
                # Atualiza padrões ativos
                self.padroes_ativos = novos_padroes
                self.ultima_atualizacao = datetime.now().strftime("%H:%M:%S")
                self.ciclos_rodados += 1
                
                # Calcula sinal agregado (cor dominante nas predições)
                self.sinal_agregado = self._calcular_sinal_agregado()
                
                # Log
                if novos_padroes:
                    melhor = novos_padroes[0]
                    log.info(
                        f"⏱️  Ciclo {self.ciclos_rodados} | {len(novos_padroes)} padrões | "
                        f"Top WR={melhor.winrate*100:.1f}% | "
                        f"Agregado={self.sinal_agregado} | "
                        f"{self.ultima_atualizacao}"
                    )
                else:
                    log.warning(
                        f"⏱️  Ciclo {self.ciclos_rodados} | Nenhum padrão atende critérios"
                    )
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"FastPatternMiner40s loop erro: {e}")
    
    def _minerar_ciclo(self, historia: List[str]) -> List[PatternInfo]:
        """
        Recalcula padrões do zero para este ciclo.
        
        Args:
            historia: lista de cores ["V", "P", "V", "B", ...]
        
        Returns:
            Lista de PatternInfo ordenada por score desc (mantém TOP 40)
        """
        # Extrai VP (ignora branco)
        vp_apenas = [c for c in historia if c in ("V", "P")]
        
        # Pega últimas JANELA_RODADAS
        if len(vp_apenas) > self.JANELA_RODADAS:
            vp_apenas = vp_apenas[-self.JANELA_RODADAS:]
        
        # Contagem: {(sequência, próxima_cor): contagem}
        contadores = {}
        for tamanho in self.TAMANHOS:
            for i in range(len(vp_apenas) - tamanho):
                seq = tuple(vp_apenas[i : i + tamanho])
                prox = vp_apenas[i + tamanho]
                chave = (seq, prox)
                contadores[chave] = contadores.get(chave, 0) + 1
        
        # Agrupa por padrão (sequência) e calcula WR
        padroes_dict = {}  # {padrão: {"V": count, "P": count}}
        for (seq, prox), cnt in contadores.items():
            if seq not in padroes_dict:
                padroes_dict[seq] = {"V": 0, "P": 0}
            if prox in ("V", "P"):
                padroes_dict[seq][prox] += cnt
        
        # Converte para PatternInfo
        candidatos = []
        for seq, votos in padroes_dict.items():
            tv = votos.get("V", 0)
            tp = votos.get("P", 0)
            total = tv + tp
            
            # Filtro 1: mínimo de ocorrências
            if total < self.MIN_OCORRENCIAS:
                continue
            
            # Melhor previsão
            melhor_pred = "V" if tv >= tp else "P"
            wins = max(tv, tp)
            wr = wins / total
            
            # Filtro 2: mínimo de WR
            if wr < self.MIN_WINRATE:
                continue
            
            candidatos.append(PatternInfo(
                pattern=seq,
                prediction=melhor_pred,
                winrate=wr,
                wins=wins,
                total=total
            ))
        
        # Ordena por score desc
        candidatos.sort(key=lambda p: -p.score())
        
        # Mantém TOP 40
        top_40 = candidatos[: self.TOP_KEEP]
        
        return top_40
    
    def _calcular_sinal_agregado(self) -> str:
        """
        Calcula cor dominante nas predições dos top 40.
        Se mais padrões preveem V, retorna "V"; se P, retorna "P".
        Se empatado, prefere "V" por padrão.
        
        Returns: "V" ou "P" ou None se vazio
        """
        if not self.padroes_ativos:
            return None
        
        votos_v = sum(1 for p in self.padroes_ativos if p.prediction == "V")
        votos_p = sum(1 for p in self.padroes_ativos if p.prediction == "P")
        
        return "V" if votos_v >= votos_p else "P"
    
    def get_top_patterns(self) -> List[Dict]:
        """
        Retorna os top padrões ativos em formato dicionário (para serialização/log).
        
        Returns:
            [
              {"pattern": [V,P,V,P,V], "pred": "P", "wr": 0.82, "wins": 23, "total": 28},
              ...
            ]
        """
        return [
            {
                "pattern": list(p.pattern),
                "pred": p.prediction,
                "wr": p.winrate,
                "wins": p.wins,
                "total": p.total,
            }
            for p in self.padroes_ativos
        ]
    
    def resumo_ciclo(self) -> str:
        """
        Retorna um resumo formatado do ciclo atual (em Telegram).
        """
        if not self.padroes_ativos:
            return (
                f"⏱️  <b>Ciclo {self.ciclos_rodados}</b> — {self.ultima_atualizacao}\n"
                f"─ Nenhum padrão atende critérios (WR≥78%, oc≥6)"
            )
        
        top3 = self.padroes_ativos[:3]
        emoji_cor = {"V": "🔴", "P": "⚫"}
        
        linhas = []
        for i, p in enumerate(top3, 1):
            cores_str = "".join(emoji_cor.get(c, c) for c in p.pattern)
            pred_emoji = emoji_cor.get(p.prediction, "?")
            linhas.append(
                f"  {i}. {cores_str} → {pred_emoji}  "
                f"WR={p.winrate*100:.1f}% ({p.wins}W/{p.total-p.wins}L)"
            )
        
        top_str = "\n".join(linhas)
        agg = emoji_cor.get(self.sinal_agregado, "?") if self.sinal_agregado else "?"
        
        return (
            f"⏱️  <b>FastMiner40s — Ciclo {self.ciclos_rodados}</b>\n"
            f"─────────────────────────────\n"
            f"📊 <b>{len(self.padroes_ativos)}</b> padrões ativos (top 40)\n"
            f"🎯 Sinal agregado: <b>{agg}</b>\n"
            f"🕐 {self.ultima_atualizacao}\n"
            f"─────────────────────────────\n"
            f"<b>TOP 3:</b>\n"
            f"{top_str}\n"
            f"<i>WR mín=78% | Oc mín=6 | Janela=300 rodadas | Recalcula a cada 40s</i>"
        )


# ══════════════════════════════════════════════════════════════════
# Função auxiliar para iniciar (chamada no main do bot)
# ══════════════════════════════════════════════════════════════════

async def iniciar_miner_40s(bot_instance) -> FastPatternMiner40s:
    """
    Cria e inicia uma instância do minerador 40s.
    Deve ser chamada dentro de uma função async durante startup do bot.
    
    Args:
        bot_instance: instância de BlazeBot (precisa ter .history_buffer)
    
    Returns:
        FastPatternMiner40s já rodando
    """
    miner = FastPatternMiner40s()
    await miner.iniciar(lambda: bot_instance.history_buffer)
    return miner
