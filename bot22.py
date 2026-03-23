import json
import asyncio
import configparser
import sys
import os
import logging
import math
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel

# ── Módulo Vermelho Engine (padrões 100% vermelho puro) ───────────
try:
    from vermelho_engine import _vermelho_engine, CONF_MINIMA_SINAL, V as VE_V
    from vermelho_integrador import VermelhoBotIntegrator, salvar_padroes_vermelho_json
    _VERMELHO_ENGINE_DISPONIVEL = True
except ImportError as _ve_err:
    _VERMELHO_ENGINE_DISPONIVEL = False
    logging.getLogger("BlazeBotVP").warning(
        f"⚠️ VermelhoEngine não carregado: {_ve_err}"
    )

# ── Módulo de estatísticas por número (0–14) ──────────────────────
try:
    from numero_stats import _numero_stats, _grupo_seco
    _NUMERO_STATS_DISPONIVEL = True
except ImportError:
    _NUMERO_STATS_DISPONIVEL = False
    logging.getLogger("BlazeBotVP").warning("⚠️ numero_stats.py não encontrado")

if sys.platform == "win32":
    try:
        os.system("chcp 65001 >nul")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("blaze_bot_vp.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("BlazeBotVP")

# ══════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES GERAIS
# ══════════════════════════════════════════════════════════════════

CORES_ATIVAS = ("V", "P")

COLOR_API_TO_LETTER         = {0: "B", 1: "V", 2: "P"}
COLOR_LETTER_TO_API         = {"V": 1, "P": 2, "B": 0}
COLOR_LETTER_TO_EMOJI       = {"B": "⚪️", "V": "🔴", "P": "⚫️"}
COLOR_LETTER_TO_LABEL       = {"B": "Branco", "V": "Vermelho", "P": "Preto"}
COLOR_LETTER_TO_ENTRY_EMOJI = {"V": "🔴", "P": "⚫️", "B": "⚪️"}
COLOR_PAYOUT                = {"V": 2.0, "P": 2.0, "B": 14.0}  # Branco paga 14x

WIN_STREAK_LIMIT       = 3
COLOR_COOLDOWN_SECONDS = 210

# AJUSTADO: Gale2 eliminado — winrate 65% < break-even 66.7% = EV negativo
GALE_MAX_VERMELHO = 1
# Estatística: 39W/21L no gale2 → corrói banca a longo prazo
GALE_MAX_PRETO    = 1

AB_REPORT_INTERVAL = 11

AUTO_LEARN_MAX_CONS_LOSS  = 3
AUTO_LEARN_MIN_WINRATE    = 60.0
AUTO_LEARN_MIN_TOTAL_EVAL = 15

AUTO_LEARN_PAT_SIZES = [5, 6]

AUTO_LEARN_MIN_ROUNDS_A   = 11
AUTO_LEARN_MIN_ACCURACY_A = 100.0
AUTO_LEARN_DB_FILE_A      = "candidatos_lista_A_em_teste.json"

AUTO_LEARN_MIN_ROUNDS_B   = 11
AUTO_LEARN_MIN_ACCURACY_B = 100.0
AUTO_LEARN_DB_FILE_B      = "candidatos_lista_B_em_teste.json"

AUTO_LEARN_MIN_ROUNDS_C   = 11
AUTO_LEARN_MIN_ACCURACY_C = 100.0
AUTO_LEARN_DB_FILE_C      = "candidatos_lista_C_em_teste.json"

AUTO_LEARN_MIN_ROUNDS_D   = 11
AUTO_LEARN_MIN_ACCURACY_D = 100.0
AUTO_LEARN_DB_FILE_D      = "candidatos_lista_D_em_teste.json"

MINERADOR_PAGINAS         = 500
MINERADOR_MIN_OCORRENCIAS = 11   # Nível 1 (padrão)
MINERADOR_MIN_WINRATE     = 1.00
MINERADOR_TAMANHOS        = [5, 6]
MINERADOR_INTERVALO_HORAS = 0.5  # ← 30 minutos (era 6 horas)

# ── Minerador em Tempo Real ───────────────────────────────────────
# A cada rodada analisa o buffer recente e atualiza padrões na memória
# Não depende de arquivo JSON — padrões criados do histórico ao vivo
MINER_RT_ATIVO          = True   # liga/desliga o minerador em tempo real
MINER_RT_JANELA         = 300    # últimas N rodadas VP para minerar
MINER_RT_MIN_OC         = 6      # mínimo de ocorrências para o padrão ser válido
MINER_RT_MIN_WR         = 0.78   # WR mínimo: 78% — só padrões fortes entram
MINER_RT_TAMANHOS       = [5, 6] # tamanhos de padrão
MINER_RT_MAX_PADROES    = 40     # máximo de padrões ativos na memória ao mesmo tempo
MINER_RT_A_CADA_RODADAS = 5      # roda o minerador a cada N rodadas novas

# ── Minerador multi-nível (rodízio automático) ─────────────────────
MINERADOR_NIVEIS = [
    {"ocorrencias": 11, "winrate": 1.00, "label": "Nível-11"},
    {"ocorrencias": 12, "winrate": 1.00, "label": "Nível-12"},
    {"ocorrencias": 13, "winrate": 1.00, "label": "Nível-13"},
]

# ── Sistema de Gestão de Banca por tipo de entrada ─────────────────
# AJUSTADO POR ESTATÍSTICA REAL:
#   Direto: 128W/0L  = 100.0% winrate → entrada agressiva 40%
#   Gale1:   85W/26L =  76.6% winrate → entrada moderada 25%
#   Gale2:   39W/21L =  65.0% winrate → BLOQUEADO (abaixo break-even 66.7%)
# Win direto (sem gale): +40% da banca; Loss direto: -35%
BANCA_WIN_DIRETO_PCT   =  0.40
BANCA_LOSS_DIRETO_PCT  = -0.35
# Win Gale 1 (2ª tentativa): +25%; Loss Gale 1: -20%
BANCA_WIN_GALE1_PCT    =  0.25
BANCA_LOSS_GALE1_PCT   = -0.20
# Gale 2 DESATIVADO — EV negativo confirmado (65% < 66.7% break-even)
# Mantidos como referência mas GALE_MAX bloqueará uso
BANCA_WIN_GALE2_PCT    =  0.10
BANCA_LOSS_GALE2_PCT   = -0.10

# ── Padrão de cor (quantidade 5 ou 6): acertou +10%, errou -10% ───
BANCA_COR_DOMINANTE_WIN_PCT  =  0.10
BANCA_COR_DOMINANTE_LOSS_PCT = -0.10

# ── Relatório automático a cada 3 minutos ─────────────────────────
RELATORIO_INTERVALO_SEG = 180   # 3 minutos

JANELA_SINAIS          = 11

MAX_LOSSES_NA_JANELA   = 4
LOSS_BLOCK_IMEDIATO_SEG = 1800  # ← 30 minutos (era 0 = desativado)

# ── Proteção contra loss consecutivo ─────────────────────────────────
# Após N losses seguidos → pausa automática de X minutos
CONSEC_LOSS_LIMITE      = 2      # 2 losses seguidos = pausa imediata
CONSEC_LOSS_PAUSA_SEG   = 0      # SEM pausa — apenas 1 sinal bloqueado
CONSEC_LOSS_ALERTA      = True   # envia alerta no Telegram

COOLDOWN_RODADAS_POS_LOSS = 1
CONSENSO_MIN_LISTAS    = 1   # Filtro 4: basta 1 lista para gerar sinal

# ── Filtro EV mínimo ─────────────────────────────────────────────
EV_MINIMO_SINAL        = 0.40  # descarta sinais com EV abaixo desse valor

# ── Sistema de 3 Categorias por WinRate ──────────────────────────────────
# CAT 1 ELITE:   WR >= 80% — entra normalmente
# CAT 2 SÓLIDA:  WR 68-80% — só entra se o padrão atual (ativo) deu loss
# CAT 3 RESERVA: WR 50-68% — só entra se o sinal veio de CAT2 e deu loss também
# Lógica: após loss, sobe para padrão de categoria melhor automaticamente
# ── Sistema de Categorias por Resultado (não por WR) ────────────────────
# CAT 1 = estado inicial — bot entrou e ganhou na 1ª tentativa
# CAT 2 = deu 1 loss    — sobe para CAT2 imediatamente
# CAT 3 = deu 2 losses  — sobe para CAT3 imediatamente
# WIN em qualquer categoria → volta direto para CAT1
# Não tem bloqueio, não tem filtro de WR — só acompanha resultado
CAT_LABELS = {1: "PRIMEIRA", 2: "SEGUNDA", 3: "TERCEIRA"}
CAT_EMOJIS = {1: "🥇", 2: "🥈", 3: "🥉"}

# ── Filtro 2: Autocorrelação de Pearson ───────────────────────────
# Correlação mínima entre sequência histórica e previsão do padrão.
# Abaixo desse limiar o sinal é descartado.
AUTOCORR_JANELA          = 15    # últimas N rodadas VP para calcular
AUTOCORR_LIMIAR          = -1.00 # desativado — só bloqueia correlação perfeita negativa
AUTOCORR_MIN_AMOSTRAS    = 8     # mínimo de rodadas para calcular

# ── Filtro 3: Bias pós-branco ─────────────────────────────────────
# Após um branco, as próximas rodadas têm viés para a cor oposta
# à que saiu antes do branco.
BIAS_POS_BRANCO_JANELA   = 4     # rodadas de influência após branco
BIAS_POS_BRANCO_ATIVO    = False # desativado

# ── Filtro 1: Entropia dos bytes do hash ─────────────────────────
# Calcula entropia de Shannon dos últimos resultados.
# Alta entropia = mercado caótico → sinal bloqueado.
ENTROPIA_HASH_JANELA     = 10    # últimas N rodadas para calcular (janela curta = mais sensível)
ENTROPIA_HASH_LIMIAR     = 1.000 # DESATIVADO

HORA_RUIM_JANELA_MIN   = 30
HORA_RUIM_LOSS_MAX     = 0.30
HORA_RUIM_PAUSA_MIN    = 15
MARKOV_CANCEL_CONF     = 0.65
CONSERVADOR_SCORE_MIN  = 75
CONSERVADOR_ACC_DIA_MIN = 85.0

HORA_BLOCK_WINRATE_MIN  = 0.40
HORA_BLOCK_MIN_AMOSTRAS = 5

MOTOR_MIN_INDICADORES_OK = 3

# ══════════════════════════════════════════════════════════════════
# FILTROS ADICIONAIS DE ASSERTIVIDADE
# ══════════════════════════════════════════════════════════════════

# ── Filtro 1: Hora Quente/Fria ────────────────────────────────────
# Horas com winrate < HORA_QUENTE_MIN são bloqueadas globalmente.
# Baseado no winrate ACUMULADO de TODOS os padrões naquela hora.
# Dados reais: 07h=67%, 15h=68% (ruins) | 21h=93%, 06h=92% (ótimas)
HORA_QUENTE_MIN_WR    = 0.70   # ← ATIVADO — bloqueia horas com WR < 70%
HORA_QUENTE_MIN_AMOSTRAS = 10  # mínimo de entradas na hora para julgar

# ── Filtro 2: Streak do Padrão ────────────────────────────────────
# Padrão com loss_streak >= N é bloqueado temporariamente.
# Max loss_streak real nos dados = 2, então >= 2 já é sinal de alerta.
STREAK_LOSS_BLOCK    = 2       # ← ATIVADO — bloqueia padrão com 2+ losses seguidos

# ── Filtro 3: Sequência Atual Seca ───────────────────────────────
# Se a sequência das últimas 4 cores VP está em máxima histórica seca
# (nunca ficou tanto tempo sem sair), o mercado está em estado incomum
# → reduz confiança (não bloqueia, mas exige score maior)
SEQ_SECA_PCT_ALERTA  = 95      # % do recorde que dispara penalidade de score
SEQ_SECA_SCORE_PENALIDADE = 0  # DESATIVADO

# ── Filtro 4: Frequência Recente do Padrão ───────────────────────
# Se o padrão apareceu >= N vezes nas últimas M rodadas → fase quente → bônus
# Se apareceu 0 vezes nas últimas M rodadas → fase seca → penalidade
FREQ_RECENTE_JANELA  = 50      # últimas N rodadas VP para verificar frequência
FREQ_RECENTE_QUENTE  = 3       # >= 3 aparições → bônus de score
FREQ_RECENTE_SECO    = 0       # 0 aparições → penalidade de score
FREQ_RECENTE_BONUS   = 10      # bônus quando padrão está quente
FREQ_RECENTE_PENALIDADE = 0    # DESATIVADO

# ── Filtro 5: Double Confirmation Padrão + Regime ────────────────
# Só entra quando a predição do padrão e o regime apontam para a mesma direção.
# TRENDING vermelho → só aceita predição V
# TRENDING preto   → só aceita predição P
# ALTERNATING      → só aceita predição oposta à última cor
# CHAOTIC          → sem confirmação de regime (já tem score mínimo maior)
DOUBLE_CONF_ATIVO    = True    # ← ATIVADO — confirma padrão com regime
DOUBLE_CONF_REGIME_MIN_CONF = 0.80  # AJUSTADO: era 0.70 — só bloqueia com regime muito forte (≥80%)

SCORE_MIN_INICIAL  = 35   # ← AUMENTADO (era 10) — filtra sinais fracos
SCORE_MIN_TETO     = 20   # teto maximo (loss empurra ate aqui)
SCORE_MIN_FLOOR    = 30   # ← AUMENTADO (era 8) — nunca cai abaixo de 30
SCORE_MIN_PASSO    = 1    # loss=+1 (mais exigente) / win=-1 (mais facil)

# ── Proteção de cold-start e score mínimo absoluto ────────────────
# COLDSTART: ignora sinais nas primeiras N rodadas reais (engines precisam
#            de dados reais para sair do aquecimento sintético)
COLDSTART_MIN_RODADAS = 5    # apenas 5 rodadas de aquecimento antes do 1º sinal

# SCORE_ABSOLUTO_MIN: floor absoluto — nenhum sinal passa abaixo disso,
# independente de motor indeciso ou padrão novo
SCORE_ABSOLUTO_MIN    = 0    # DESATIVADO

# CHAOTIC_SCORE_MIN: em regime caótico, exige score mais alto ainda
CHAOTIC_SCORE_MIN     = 0    # DESATIVADO

# ── Janela de exclusão de padrão ─────────────────────────────────
# Padrão é excluído APENAS se der 2 losses CONSECUTIVOS (seguidos).
# 1 loss isolado → apenas bloqueio temporário de 1 min, não exclui.
JANELA_EXCLUSAO_PADRAO  = 10   # mantido para referência (não usado na nova lógica)

# ── Regime Switching config ────────────────────────────────────────
REGIME_JANELA        = 20      # últimas N cores VP para detectar regime
REGIME_CONF_MIN      = 0.65    # confiança mínima para declarar regime
# Nomes dos regimes: "trending" | "alternating" | "chaotic"

import hashlib as _hashlib

_NP1 = [
    "BLA","FLA","TRO","VEN","COR","PRI","SOL","LUN","RAI","FOG",
    "TEM","MAR","PED","FER","CAL","GEL","VUL","CAN","SER","TOR",
    "AQU","FUR","NEV","ARC","BOR","CRU","DRA","ESP","FAL","GRI",
    "HUR","JAV","KRY","LAV","MEL","NAR","ORC","PAL","QUI","RAN",
    "SAB","TAL","URB","VAL","ZAF","ALT","BRU","CUR","FOX","RUX",
]
_NP2 = [
    "ACE","ORA","ELA","URA","INA","ANO","EMO","ULO","AGA","OCA",
    "ETA","AMA","ONE","ITO","ARA","ENO","UNA","OLA","EDA","AVO",
    "ICO","OKA","UMO","ANE","ERI","IRO","OSA","UTE","ALE","EMA",
    "IMO","ONA","AVE","IGA","UME","ARI","INO","OKE","ATO","EMU",
    "IRA","AZE","OBO","UBI","AJO","EXO","IFO","ODO","AGO","UNO",
]
_NP3 = [
    "DOR","TOR","NOR","VOR","ZOR","LOR","COR","ROR","GOR","SOR",
    "DES","TES","NES","VES","ZES","LES","CES","RES","GES","SES",
    "DAN","TAN","NAN","VAN","ZAN","LAN","CAN","RAN","GAN","SAN",
    "DAR","TAR","NAR","VAR","ZAR","LAR","CAR","RAR","GAR","SAR",
    "DON","TON","NON","VON","ZON","LON","CON","RON","GON","SON",
]

def _candidato_nome(pattern: list, prediction: str, tentativa: int = 0) -> str:
    raw = json.dumps([list(pattern), prediction, tentativa], ensure_ascii=False)
    h   = int(_hashlib.sha256(raw.encode()).hexdigest(), 16)
    return _NP1[h % 50] + _NP2[(h >> 16) % 50] + _NP3[(h >> 32) % 50]

PATTERN_DB_FILE = "banco_estatisticas_padroes.json"

# ══════════════════════════════════════════════════════════════════
# MÓDULO BRANCO — BrancoDetector
# Analisa os rolls (números) antes de cada branco e descobre
# quais fórmulas matemáticas resultam em 0 ou múltiplo de 14.
# Salva padrões descobertos em: branco.json
# Avisa no Telegram quando detecta iminência de branco.
# ══════════════════════════════════════════════════════════════════

class BrancoDetector:
    """
    Para cada branco no histórico, pega os 5 ou 6 rolls anteriores
    e testa dezenas de fórmulas matemáticas.
    Se uma fórmula resultar em 0 (exato) ou próximo de 0 com
    alta frequência, ela é salva como padrão preditivo.

    Em tempo real: a cada rodada aplica os padrões descobertos
    nos rolls recentes e avisa se há risco de branco iminente.
    """
    DB_FILE    = "branco.json"
    JANELAS    = [2, 3]
    TOLERANCIA = 0.5   # margem para considerar "resultado ≈ 0"
    MIN_TAXA   = 0.12  # 12% mínimo para considerar padrão válido
    MIN_ACERTOS = 3    # mínimo de brancos confirmados

    def __init__(self):
        self._padroes: list = []
        self._historico_rolls: list = []  # [(cor, roll), ...]
        self._alertas_emitidos: int = 0
        self._brancos_previstos: int = 0
        self._brancos_total: int = 0
        self._load()

    def _load(self):
        if os.path.exists(self.DB_FILE):
            try:
                with open(self.DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._padroes = data.get("padroes", [])
                self._alertas_emitidos  = data.get("alertas_emitidos", 0)
                self._brancos_previstos = data.get("brancos_previstos", 0)
                self._brancos_total     = data.get("brancos_total", 0)
                log.info(f"BrancoDetector: {len(self._padroes)} padrões carregados de {self.DB_FILE}")
            except Exception as e:
                log.error(f"BrancoDetector load: {e}")

    def _save(self, historico_analise: list = None):
        try:
            data = {
                "padroes": self._padroes,
                "alertas_emitidos":  self._alertas_emitidos,
                "brancos_previstos": self._brancos_previstos,
                "brancos_total":     self._brancos_total,
                "ultima_atualizacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            if historico_analise:
                data["historico_analise"] = historico_analise[:100]
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"BrancoDetector save: {e}")

    # ── 53 Fórmulas matemáticas testadas ─────────────────────────
    @staticmethod
    def _aplicar_formulas(nums: list) -> list:
        """Retorna lista de (nome_formula, valor) para os nums dados.
        Otimizado para 2 ou 3 números anteriores ao branco.
        """
        import functools
        n = nums
        L = len(n)
        s = sum(n)
        mn, mx = min(n), max(n)
        media = s / L
        res = []

        # ── Grupo 1: Somas e módulos ──────────────────────────────
        res.append(("soma",                  s))
        res.append(("soma_mod14",            s % 14))
        res.append(("soma_mod7",             s % 7))
        res.append(("soma_mod6",             s % 6))
        res.append(("soma_mod5",             s % 5))
        res.append(("soma_mod3",             s % 3))
        res.append(("soma_mod2",             s % 2))

        # ── Grupo 2: Médias e arredondamentos ─────────────────────
        res.append(("media_round",           round(media)))
        res.append(("media_floor",           int(media)))
        res.append(("media_ceil",            math.ceil(media)))
        res.append(("media_mod14",           round(media) % 14))

        # ── Grupo 3: Diferenças e deltas ─────────────────────────
        res.append(("max_minus_min",         mx - mn))
        res.append(("ultimo_menos_primeiro", n[-1] - n[0]))
        res.append(("primeiro_menos_ultimo", n[0] - n[-1]))
        res.append(("abs_diferenca",         abs(n[-1] - n[0])))
        res.append(("diff_max_media",        round(abs(mx - media))))
        res.append(("diff_min_media",        round(abs(mn - media))))

        # ── Grupo 4: Somas parciais ───────────────────────────────
        res.append(("soma_pares",            sum(x for x in n if x % 2 == 0)))
        res.append(("soma_impares",          sum(x for x in n if x % 2 != 0)))
        res.append(("soma_ultimos2",         n[-1] + n[-2] if L >= 2 else n[-1]))
        res.append(("soma_ultimos3",         sum(n[-3:]) if L >= 3 else s))
        res.append(("soma_meio",             n[1] if L >= 3 else 0))

        # ── Grupo 5: Produtos ─────────────────────────────────────
        res.append(("produto",              (n[0] * n[1]) if L >= 2 else n[0]))
        res.append(("produto_mod14",        (n[0] * n[1]) % 14 if L >= 2 else 0))
        res.append(("produto_mod7",         (n[0] * n[1]) % 7  if L >= 2 else 0))
        try:
            prod = functools.reduce(lambda a, b: a * b, n)
            res.append(("produto_todos_mod14",   prod % 14))
            res.append(("produto_todos_mod7",    prod % 7))
        except Exception:
            res.append(("produto_todos_mod14",   0))
            res.append(("produto_todos_mod7",    0))

        # ── Grupo 6: Operações bit a bit ─────────────────────────
        res.append(("xor_todos",             functools.reduce(lambda a, b: a ^ b, n)))
        res.append(("and_todos",             functools.reduce(lambda a, b: a & b, n)))
        res.append(("or_todos",              functools.reduce(lambda a, b: a | b, n)))
        res.append(("xor_mod14",             functools.reduce(lambda a, b: a ^ b, n) % 14))
        res.append(("and_mod14",             functools.reduce(lambda a, b: a & b, n) % 14))

        # ── Grupo 7: Quadrados e raízes ───────────────────────────
        res.append(("soma_quadrados",        sum(x*x for x in n)))
        res.append(("soma_quadrados_mod14",  sum(x*x for x in n) % 14))
        res.append(("soma_quadrados_mod7",   sum(x*x for x in n) % 7))
        res.append(("sqrt_soma_round",       round(math.sqrt(s)) if s >= 0 else 0))
        res.append(("sqrt_soma_mod14",       round(math.sqrt(s)) % 14 if s >= 0 else 0))
        res.append(("diff_quadrados",        abs(n[0]*n[0] - n[-1]*n[-1])))
        res.append(("diff_quadrados_mod14",  abs(n[0]*n[0] - n[-1]*n[-1]) % 14))

        # ── Grupo 8: Alternâncias ────────────────────────────────
        res.append(("soma_alternada",        sum(x if i%2==0 else -x for i,x in enumerate(n))))
        res.append(("soma_alternada_abs",    abs(sum(x if i%2==0 else -x for i,x in enumerate(n)))))
        res.append(("soma_alternada_mod14",  abs(sum(x if i%2==0 else -x for i,x in enumerate(n))) % 14))

        # ── Grupo 9: Posições e contagens ────────────────────────
        res.append(("zeros_na_janela",       n.count(0)))
        res.append(("posicao_max",           n.index(mx)))
        res.append(("posicao_min",           n.index(mn)))
        res.append(("qtd_distintos",         len(set(n))))
        res.append(("iguais",                1 if len(set(n)) == 1 else 0))

        # ── Grupo 10: Fórmulas compostas ─────────────────────────
        dma = sum(abs(x - media) for x in n) / L
        res.append(("desvio_medio_abs_round", round(dma)))
        res.append(("desvio_medio_abs_mod14", round(dma) % 14))
        soma_dig = sum(sum(int(d) for d in str(x)) for x in n)
        res.append(("soma_digitos",           soma_dig))
        res.append(("soma_digitos_mod14",     soma_dig % 14))
        sp = sum(x for x in n if x % 2 == 0)
        si = sum(x for x in n if x % 2 != 0)
        res.append(("diff_pares_impares",     abs(sp - si)))
        res.append(("diff_pares_impares_mod14", abs(sp - si) % 14))

        return res



    # ── Mineração sobre histórico ────────────────────────────────
    def minerar(self, historico: list) -> int:
        """
        Recebe lista de {'cor': 'B'/'V'/'P', 'roll': int}.
        Testa todas as fórmulas para cada janela de 5 e 6 antes do branco.
        Atualiza self._padroes com os mais fortes.
        Retorna quantidade de padrões novos encontrados.
        """
        from collections import defaultdict
        stats = defaultdict(lambda: {"acertos": 0, "total": 0, "exemplos": []})

        brancos = 0
        for i, rod in enumerate(historico):
            if rod["cor"] != "B":
                continue
            brancos += 1
            self._brancos_total = brancos

            for jan in self.JANELAS:
                if i < jan:
                    continue
                nums = [historico[i - jan + j]["roll"] for j in range(jan)]
                if any(r is None for r in nums):
                    continue

                for nome, valor in self._aplicar_formulas(nums):
                    # Testa contra todos os alvos relevantes para o Double
                    # Rolls vão de 0 a 14; testamos 0, 1, 2, 7, 14 e múltiplos
                    for alvo in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]:
                        chave = (jan, nome, f"=={alvo}")
                        stats[chave]["total"] += 1
                        if abs(float(valor) - alvo) <= self.TOLERANCIA:
                            stats[chave]["acertos"] += 1
                            if len(stats[chave]["exemplos"]) < 5:
                                stats[chave]["exemplos"].append(
                                    {"nums": nums, "resultado": round(float(valor), 4)})

        if brancos < 3:
            log.warning("BrancoDetector: poucos brancos no histórico para minerar.")
            return 0

        # Filtra e rankeia
        novos_padroes = []
        for (jan, nome, cond), dados in stats.items():
            if dados["total"] < 3:
                continue
            taxa = dados["acertos"] / dados["total"]
            if taxa < self.MIN_TAXA or dados["acertos"] < self.MIN_ACERTOS:
                continue
            novos_padroes.append({
                "janela":   jan,
                "formula":  nome,
                "condicao": cond,
                "acertos":  dados["acertos"],
                "total":    dados["total"],
                "taxa":     round(taxa, 4),
                "taxa_pct": f"{taxa*100:.1f}%",
                "exemplos": dados["exemplos"],
            })

        novos_padroes.sort(key=lambda x: (x["taxa"], x["acertos"]), reverse=True)
        antes = len(self._padroes)
        self._padroes = novos_padroes[:30]  # guarda top 30
        novos = max(0, len(self._padroes) - antes)

        log.info(
            f"BrancoDetector: mineração concluída | "
            f"{brancos} brancos | {len(self._padroes)} padrões | "
            f"melhor={self._padroes[0]['formula'] if self._padroes else 'nenhum'} "
            f"({self._padroes[0]['taxa_pct'] if self._padroes else '—'})"
        )
        self._save()
        return novos

    # ── Detecção em tempo real ────────────────────────────────────
    def atualizar_roll(self, cor: str, roll: int) -> None:
        """Adiciona a rodada mais recente ao buffer interno."""
        self._historico_rolls.append({"cor": cor, "roll": roll})
        if len(self._historico_rolls) > 20:
            self._historico_rolls = self._historico_rolls[-20:]
        if cor == "B":
            self._brancos_total += 1

    def checar_alerta(self) -> dict:
        """
        Só emite alerta quando MÚLTIPLAS fórmulas concordam ao mesmo tempo.
        Quanto mais fórmulas concordando → mais confiável o sinal.

        Níveis de confiança:
          1 fórmula  → ignorado (muito comum, falso positivo)
          2 fórmulas → BAIXO   (20-39%)
          3 fórmulas → MÉDIO   (40-69%)
          4 fórmulas → ALTO    (70-89%)
          5+ fórmulas → MÁXIMO (90-100%)
        """
        if not self._padroes or len(self._historico_rolls) < 6:
            return {"score": 0, "alertas": [], "linha": "", "concordancias": 0}

        # Testa TODOS os padrões descobertos (não só top10)
        alertas = []
        for p in self._padroes:
            jan = p["janela"]
            if len(self._historico_rolls) < jan:
                continue
            nums = [r["roll"] for r in self._historico_rolls[-jan:]]
            if any(x is None for x in nums):
                continue
            formulas = dict(self._aplicar_formulas(nums))
            valor = formulas.get(p["formula"])
            if valor is None:
                continue
            try:
                alvo = int(p["condicao"].replace("==", ""))
            except Exception:
                alvo = 0
            if abs(float(valor) - alvo) <= self.TOLERANCIA:
                alertas.append({
                    "formula":   p["formula"],
                    "condicao":  p["condicao"],
                    "taxa":      p["taxa"],
                    "taxa_pct":  p["taxa_pct"],
                    "janela":    jan,
                    "nums":      nums,
                    "resultado": round(float(valor), 4),
                    "acertos":   p["acertos"],
                    "total":     p["total"],
                })

        n_concorda = len(alertas)

        # REGRA PRINCIPAL: menos de 2 fórmulas concordando → silêncio total
        if n_concorda < 2:
            return {"score": 0, "alertas": alertas, "linha": "", "concordancias": n_concorda}

        # Score proporcional ao número de concordâncias E à taxa média
        taxa_media = sum(a["taxa"] for a in alertas) / n_concorda

        if n_concorda >= 5:
            base_score = 90
            emoji = "🔴"
            nivel = "MÁXIMO"
        elif n_concorda == 4:
            base_score = 70
            emoji = "🟠"
            nivel = "ALTO"
        elif n_concorda == 3:
            base_score = 45
            emoji = "🟡"
            nivel = "MÉDIO"
        else:  # 2
            base_score = 22
            emoji = "🟢"
            nivel = "BAIXO"

        # Ajusta pelo taxa média real dos padrões
        score = min(100, int(base_score + (taxa_media * 20)))

        # Monta resumo das fórmulas que concordaram
        formulas_str = " | ".join(
            f"{a['formula']}{a['condicao']}={a['resultado']}"
            for a in alertas[:4]   # mostra até 4
        )
        extras = f" +{n_concorda-4} mais" if n_concorda > 4 else ""

        linha = (
            f"⚪ {emoji} <b>RISCO BRANCO {nivel} {score}%</b>  "
            f"[<b>{n_concorda} fórmulas concordam</b>]\n"
            f"   {formulas_str}{extras}\n"
            f"   nums(j5)={alertas[0]['nums']} | taxa média={taxa_media*100:.1f}%"
        )

        log.info(
            f"⚪ BRANCO ALERTA | {n_concorda} concordâncias | score={score}% | "
            f"taxa_media={taxa_media*100:.1f}%"
        )

        return {
            "score":        score,
            "alertas":      alertas,
            "concordancias": n_concorda,
            "taxa_media":   round(taxa_media, 4),
            "nivel":        nivel,
            "linha":        linha,
        }

    def registrar_alerta_enviado(self, acertou: bool) -> None:
        self._alertas_emitidos += 1
        if acertou:
            self._brancos_previstos += 1
        self._save()

    def resumo(self) -> str:
        if not self._padroes:
            return "⚪ <b>BrancoDetector</b>: aguardando mineração inicial."
        p = self._padroes[0]
        taxa_prev = (
            f"{self._brancos_previstos}/{self._alertas_emitidos} "
            f"({self._brancos_previstos/self._alertas_emitidos*100:.0f}%)"
            if self._alertas_emitidos > 0 else "—"
        )
        alerta_atual = self.checar_alerta()
        conc = alerta_atual.get("concordancias", 0)
        if conc >= 5:
            status_atual = f"🔴 {conc} concordâncias — MÁXIMO"
        elif conc == 4:
            status_atual = f"🟠 {conc} concordâncias — ALTO"
        elif conc == 3:
            status_atual = f"🟡 {conc} concordâncias — MÉDIO"
        elif conc == 2:
            status_atual = f"🟢 {conc} concordâncias — BAIXO"
        else:
            status_atual = f"✅ {conc} concordância(s) — sem alerta"
        return (
            f"⚪ <b>BrancoDetector</b>\n"
            f"   Fórmulas testadas: <b>53</b> | Alvos: <b>0-14</b>\n"
            f"   Padrões descobertos: <b>{len(self._padroes)}</b>\n"
            f"   Melhor padrão: <b>{p['formula']} {p['condicao']}</b> "
            f"({p['taxa_pct']} | {p['acertos']}/{p['total']} brancos)\n"
            f"   Brancos no histórico: <b>{self._brancos_total}</b>\n"
            f"   Previsões: <b>{taxa_prev}</b>\n"
            f"   Agora: <b>{status_atual}</b>\n"
            f"   ℹ️ Alerta só dispara com ≥2 fórmulas concordando"
        )


# Instância global
_branco_detector = BrancoDetector()


# ══════════════════════════════════════════════════════════════════
# BRANCO HISTORICO
# Registra cada ocorrência de branco com contexto completo.
# Salva em: branco_historico.json
# ══════════════════════════════════════════════════════════════════

class BrancoHistorico:
    """
    Toda vez que sai branco (0), registra:
      - hora exata
      - número (sempre 0)
      - cor anterior (V/P/B)
      - cor posterior (V/P/B) — preenchida na próxima rodada
      - sequência das últimas 6 cores VP antes do branco
      - intervalo desde o último branco (rodadas)
      - total de brancos

    Salva automaticamente em branco_historico.json.
    """

    DB_FILE = "branco_historico.json"

    def __init__(self):
        self._ocorrencias: list = []
        self._ultimo_idx: int   = 0    # índice global da última rodada
        self._buffer_cores: list = []  # últimas 10 cores para contexto
        self._ultimo_branco_idx: int = -1
        self._aguardando_pos: bool = False  # aguardando cor pós-branco
        self._load()

    def _load(self):
        if not os.path.exists(self.DB_FILE):
            return
        try:
            with open(self.DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._ocorrencias       = data.get("ocorrencias", [])
            self._ultimo_branco_idx = data.get("ultimo_branco_idx", -1)
            self._ultimo_idx        = data.get("ultimo_idx", 0)
            log.info(f"BrancoHistorico: {len(self._ocorrencias)} brancos carregados")
        except Exception as e:
            log.warning(f"BrancoHistorico load: {e}")

    def _save(self):
        total    = len(self._ocorrencias)
        # Calcula intervalo médio entre brancos
        intervalos = [
            e["intervalo_desde_ultimo"]
            for e in self._ocorrencias
            if e["intervalo_desde_ultimo"] > 0
        ]
        media_intervalo = round(sum(intervalos) / len(intervalos), 1) if intervalos else 0
        # Hora mais frequente
        horas = [e["hora"][:2] for e in self._ocorrencias]
        hora_mais_freq = max(set(horas), key=horas.count) + "h" if horas else "—"
        # Cor mais comum antes do branco
        antes = [e["cor_antes"] for e in self._ocorrencias if e["cor_antes"] in ("V","P")]
        cor_antes_freq = max(set(antes), key=antes.count) if antes else "—"
        # Cor mais comum depois do branco
        depois = [e["cor_depois"] for e in self._ocorrencias if e.get("cor_depois") in ("V","P")]
        cor_depois_freq = max(set(depois), key=depois.count) if depois else "—"

        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "total_brancos":      total,
                    "media_intervalo":    media_intervalo,
                    "hora_mais_frequente": hora_mais_freq,
                    "cor_antes_mais_freq": cor_antes_freq,
                    "cor_depois_mais_freq": cor_depois_freq,
                    "ultimo_branco_idx":  self._ultimo_branco_idx,
                    "ultimo_idx":         self._ultimo_idx,
                    "ultima_atualizacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ocorrencias":        self._ocorrencias[-1000:],
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning(f"BrancoHistorico save: {e}")

    def registrar_rodada(self, cor: str, numero: int) -> None:
        """Deve ser chamado a cada rodada com a cor e número reais."""
        if cor not in ("V", "P", "B"):
            return

        self._ultimo_idx += 1

        # Preenche cor_depois do branco anterior
        if self._aguardando_pos and self._ocorrencias:
            self._ocorrencias[-1]["cor_depois"] = cor
            self._aguardando_pos = False

        if cor == "B":
            # Calcula intervalo desde o último branco
            intervalo = (
                self._ultimo_idx - self._ultimo_branco_idx - 1
                if self._ultimo_branco_idx >= 0 else -1
            )

            # Sequência das últimas 6 cores (excluindo o branco atual)
            seq = list(self._buffer_cores[-6:])

            # Cor imediatamente antes
            cor_antes = self._buffer_cores[-1] if self._buffer_cores else "?"

            entrada = {
                "id":                    len(self._ocorrencias) + 1,
                "hora":                  datetime.now().strftime("%H:%M:%S"),
                "data":                  datetime.now().strftime("%d/%m/%Y"),
                "numero":                numero,
                "cor_antes":             cor_antes,
                "cor_depois":            None,   # preenchido na próxima rodada
                "sequencia_antes":       seq,
                "intervalo_desde_ultimo": intervalo,
                "rodada_idx":            self._ultimo_idx,
            }
            self._ocorrencias.append(entrada)
            self._ultimo_branco_idx = self._ultimo_idx
            self._aguardando_pos    = True
            self._save()

        # Atualiza buffer (só VP para sequência)
        if cor in ("V", "P"):
            self._buffer_cores.append(cor)
            if len(self._buffer_cores) > 10:
                self._buffer_cores = self._buffer_cores[-10:]

    def resumo(self) -> str:
        """Relatório completo para o Telegram."""
        if not self._ocorrencias:
            return "⚪ <b>Branco Histórico</b>: sem registros ainda."

        total    = len(self._ocorrencias)
        CE       = {"V": "🔴", "P": "⚫", "B": "⚪", "?": "❓", None: "⏳"}

        # Intervalo médio
        intervalos = [
            e["intervalo_desde_ultimo"]
            for e in self._ocorrencias if e["intervalo_desde_ultimo"] > 0
        ]
        media  = round(sum(intervalos) / len(intervalos), 1) if intervalos else 0
        minimo = min(intervalos) if intervalos else 0
        maximo = max(intervalos) if intervalos else 0

        # Seco atual (rodadas desde o último branco)
        seco_atual = self._ultimo_idx - self._ultimo_branco_idx - 1 if self._ultimo_branco_idx >= 0 else 0

        # Cor antes
        antes = [e["cor_antes"] for e in self._ocorrencias if e["cor_antes"] in ("V","P")]
        cnt_av = antes.count("V")
        cnt_ap = antes.count("P")

        # Cor depois
        depois = [e["cor_depois"] for e in self._ocorrencias if e.get("cor_depois") in ("V","P")]
        cnt_dv = depois.count("V")
        cnt_dp = depois.count("P")

        # Horas mais frequentes
        from collections import Counter
        horas_cnt = Counter(e["hora"][:2] for e in self._ocorrencias)
        top_horas = ", ".join(f"{h}h({c})" for h, c in horas_cnt.most_common(3))

        # Últimas 8 ocorrências
        linhas = []
        for e in self._ocorrencias[-8:]:
            seq_str = "".join(CE.get(c, c) for c in e["sequencia_antes"][-4:])
            antes_e = CE.get(e["cor_antes"], "?")
            depois_e = CE.get(e.get("cor_depois"), "⏳")
            intv    = e["intervalo_desde_ultimo"]
            intv_str = f"{intv}r" if intv >= 0 else "1º"
            linhas.append(
                f"  #{e['id']}  {e['hora']}  {seq_str}→⚪←{depois_e}  "
                f"intv:{intv_str}"
            )

        return (
            f"⚪ <b>Histórico de Brancos</b>\n"
            f"{'─' * 22}\n"
            f"Total: <b>{total}</b>  │  Seco atual: <b>{seco_atual}</b> rodadas\n\n"
            f"⏱️ Intervalo  mín: <b>{minimo}</b>  méd: <b>{media}</b>  máx: <b>{maximo}</b>\n\n"
            f"🎨 Antes do branco:\n"
            f"   🔴 Vermelho: <b>{cnt_av}</b> ({cnt_av/max(1,len(antes))*100:.0f}%)  "
            f"⚫ Preto: <b>{cnt_ap}</b> ({cnt_ap/max(1,len(antes))*100:.0f}%)\n\n"
            f"🎨 Depois do branco:\n"
            f"   🔴 Vermelho: <b>{cnt_dv}</b> ({cnt_dv/max(1,len(depois))*100:.0f}%)  "
            f"⚫ Preto: <b>{cnt_dp}</b> ({cnt_dp/max(1,len(depois))*100:.0f}%)\n\n"
            f"🕐 Horas mais frequentes: {top_horas}\n"
            f"{'─' * 22}\n"
            f"<b>Últimas 8 ocorrências:</b>\n"
            + "\n".join(linhas)
        )


_branco_hist = BrancoHistorico()


# ══════════════════════════════════════════════════════════════════
# BRANCO STATS
# Registra cada saída de branco com: hora, número, cor anterior,
# intervalo desde o último branco, e acumula estatísticas históricas.
# Salva em: branco_stats.json
# ══════════════════════════════════════════════════════════════════

class BrancoStats:
    """
    Para cada branco que sai, registra:
      - hora        : HH:MM:SS
      - numero      : número exato (0)
      - cor_antes   : cor que saiu imediatamente antes
      - intervalo   : quantas rodadas desde o último branco
      - rodada_total: índice global da rodada

    Estatísticas acumuladas:
      - média de intervalo entre brancos
      - maior intervalo (seco máximo)
      - seco atual (rodadas desde o último branco)
      - distribuição por hora do dia
      - cor mais comum antes do branco
    """

    DB_FILE = "branco_stats.json"

    def __init__(self):
        self._historico: list  = []   # lista de ocorrências
        self._rodadas_total: int = 0  # contador de rodadas (V+P+B)
        self._ultima_rodada_branco: int = -1  # índice da última vez que saiu B
        self._ultima_cor: str  = ""   # cor da rodada anterior
        self._load()

    def _load(self):
        if not os.path.exists(self.DB_FILE):
            return
        try:
            with open(self.DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._historico          = data.get("historico", [])
            self._rodadas_total      = data.get("rodadas_total", 0)
            self._ultima_rodada_branco = data.get("ultima_rodada_branco", -1)
            log.info(f"BrancoStats: {len(self._historico)} brancos carregados de {self.DB_FILE}")
        except Exception as e:
            log.warning(f"BrancoStats load: {e}")

    def _save(self):
        stats = self._calcular_stats()
        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "historico":             self._historico,
                    "rodadas_total":         self._rodadas_total,
                    "ultima_rodada_branco":  self._ultima_rodada_branco,
                    "ultima_atualizacao":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "estatisticas":          stats,
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning(f"BrancoStats save: {e}")

    def _calcular_stats(self) -> dict:
        if not self._historico:
            return {}

        intervalos = [e["intervalo"] for e in self._historico if e["intervalo"] > 0]
        horas      = [e["hora"][:2] for e in self._historico]
        cores_ant  = [e["cor_antes"] for e in self._historico if e["cor_antes"] in ("V","P")]

        # Seco atual
        seco_atual = (self._rodadas_total - self._ultima_rodada_branco - 1
                      if self._ultima_rodada_branco >= 0 else self._rodadas_total)

        # Distribuição por hora
        hora_dist = {}
        for h in horas:
            hora_dist[h] = hora_dist.get(h, 0) + 1

        # Cor mais comum antes
        cnt_v = cores_ant.count("V")
        cnt_p = cores_ant.count("P")

        return {
            "total_brancos":   len(self._historico),
            "seco_atual":      seco_atual,
            "max_seco":        max(intervalos) if intervalos else 0,
            "min_seco":        min(intervalos) if intervalos else 0,
            "media_intervalo": round(sum(intervalos) / len(intervalos), 1) if intervalos else 0,
            "antes_V":         cnt_v,
            "antes_P":         cnt_p,
            "hora_mais_comum": max(hora_dist, key=hora_dist.get) if hora_dist else "?",
            "distribuicao_hora": hora_dist,
        }

    def registrar(self, cor: str, numero: int) -> None:
        """Registra cada rodada. Quando cor == 'B', salva o evento completo."""
        self._rodadas_total += 1

        if cor == "B":
            # Calcula intervalo desde o último branco
            if self._ultima_rodada_branco >= 0:
                intervalo = self._rodadas_total - self._ultima_rodada_branco - 1
            else:
                intervalo = -1  # primeiro branco registrado

            entrada = {
                "hora":       datetime.now().strftime("%H:%M:%S"),
                "data":       datetime.now().strftime("%d/%m/%Y"),
                "numero":     numero,
                "cor_antes":  self._ultima_cor,
                "intervalo":  intervalo,
                "rodada_idx": self._rodadas_total,
            }
            self._historico.append(entrada)
            self._ultima_rodada_branco = self._rodadas_total
            self._save()
            log.info(
                f"⚪ BrancoStats: branco #{len(self._historico)} | "
                f"intervalo={intervalo} | cor_antes={self._ultima_cor} | "
                f"num={numero} | {entrada['hora']}"
            )

        self._ultima_cor = cor

    def resumo(self) -> str:
        """Relatório para exibir no Telegram."""
        stats = self._calcular_stats()
        if not stats:
            return "⚪ <b>Branco Stats</b>: sem dados ainda."

        total   = stats["total_brancos"]
        seco    = stats["seco_atual"]
        mx      = stats["max_seco"]
        mn      = stats["min_seco"]
        media   = stats["media_intervalo"]
        cnt_v   = stats["antes_V"]
        cnt_p   = stats["antes_P"]
        hora_mc = stats["hora_mais_comum"]

        # Barra do seco atual vs máximo
        pct = int(seco / max(1, mx) * 100) if mx > 0 else 0
        def _barra(p, s=8):
            return "█" * int(round(min(p,100)/100*s)) + "░" * (s - int(round(min(p,100)/100*s)))

        urg = " 🔴" if pct >= 90 else (" 🟠" if pct >= 75 else (" 🟡" if pct >= 55 else ""))

        # Últimos 10 brancos
        CE = {"V": "🔴", "P": "⚫", "B": "⚪"}
        ultimos = self._historico[-10:]
        linhas_ult = []
        for e in ultimos:
            ant = CE.get(e["cor_antes"], "?")
            iv  = e["intervalo"]
            linhas_ult.append(
                f"  {e['data']} {e['hora']}  "
                f"num:{e['numero']}  antes:{ant}  "
                f"intervalo:{iv}"
            )

        # Distribuição por hora (top 5)
        hora_dist = stats.get("distribuicao_hora", {})
        top_horas = sorted(hora_dist.items(), key=lambda x: -x[1])[:5]
        hora_txt  = "  ".join(f"{h}h:{c}" for h, c in top_horas)

        return (
            f"⚪ <b>Branco Stats — {total} brancos registrados</b>\n"
            f"{'─' * 22}\n"
            f"⏱️ Seco atual: <b>{seco}</b>  máx: <b>{mx}</b>  "
            f"<code>[{_barra(pct)}]</code>{urg}\n"
            f"📊 Média intervalo: <b>{media}</b>  mín: <b>{mn}</b>\n\n"
            f"🎨 Cor antes do branco:\n"
            f"   🔴 Vermelho: <b>{cnt_v}</b>  ⚫ Preto: <b>{cnt_p}</b>\n\n"
            f"🕐 Hora mais frequente: <b>{hora_mc}h</b>\n"
            f"📈 Top horas: {hora_txt}\n"
            f"{'─' * 22}\n"
            f"<b>Últimos 10 brancos:</b>\n"
            + "\n".join(linhas_ult)
        )


_branco_stats = BrancoStats()


# ══════════════════════════════════════════════════════════════════
# MÓDULO 1 — KellyCriterion
# Calcula o tamanho ideal de aposta baseado no winrate real do padrão.
# Salva histórico em: kelly_criterion.json
# ══════════════════════════════════════════════════════════════════

class KellyCriterion:
    """
    Critério de Kelly: f* = (p * b - q) / b
      p = probabilidade de ganhar (winrate real do padrão)
      q = probabilidade de perder (1 - p)
      b = payout líquido (ex: payout 2.0 → b=1.0)
    Retorna fração da banca a apostar (ex: 0.05 = 5% da banca).
    Limita entre 1% e 25% por segurança.
    """
    DB_FILE = "kelly_criterion.json"

    def __init__(self):
        self._historico: list = []
        self._load()

    def _load(self):
        if os.path.exists(self.DB_FILE):
            try:
                with open(self.DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._historico = data.get("historico", [])
                log.info(f"KellyCriterion: {len(self._historico)} registros carregados")
            except Exception as e:
                log.error(f"KellyCriterion load: {e}")

    def _save(self):
        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({"historico": self._historico[-500:]}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"KellyCriterion save: {e}")

    def calcular(self, wins: int, total: int, payout: float = 2.0, banca: float = 100.0) -> dict:
        if total < 5:
            return {"fracao": 0.02, "valor": round(banca * 0.02, 2),
                    "winrate": 0.0, "kelly_bruto": 0.0,
                    "linha": "📐 Kelly: <i>dados insuficientes (mín. 5)</i> — usando 2%"}
        p = wins / total
        q = 1.0 - p
        b = payout - 1.0   # lucro líquido por unidade apostada
        kelly_bruto = (p * b - q) / b if b > 0 else 0.0
        # Fração conservadora: metade do Kelly puro (Half-Kelly)
        fracao = max(0.01, min(0.25, kelly_bruto * 0.5))
        valor  = round(banca * fracao, 2)
        if kelly_bruto <= 0:
            recomendacao = "⛔ EV negativo — NÃO apostar"
            emoji = "🔴"
        elif fracao <= 0.03:
            recomendacao = "⚠️ aposta mínima"
            emoji = "🟡"
        elif fracao <= 0.10:
            recomendacao = "✅ aposta normal"
            emoji = "🟢"
        else:
            recomendacao = "🔥 aposta alta"
            emoji = "🟢"
        registro = {
            "hora": datetime.now().strftime("%H:%M:%S"),
            "wins": wins, "total": total,
            "winrate": round(p * 100, 1),
            "kelly_bruto": round(kelly_bruto, 4),
            "fracao": round(fracao, 4),
            "valor_sugerido": valor,
            "banca": banca,
        }
        self._historico.append(registro)
        self._save()
        return {
            "fracao": fracao, "valor": valor,
            "winrate": round(p * 100, 1),
            "kelly_bruto": round(kelly_bruto, 4),
            "linha": (
                f"📐 <b>Kelly</b> {emoji} <b>{fracao*100:.1f}%</b> da banca "
                f"= R$<b>{valor:.2f}</b>  "
                f"<i>(wr={p*100:.0f}% | k={kelly_bruto*100:.1f}% | {recomendacao})</i>"
            ),
        }

    def resumo(self) -> str:
        if not self._historico:
            return "📐 <b>Kelly Criterion</b>: sem dados ainda."
        ultimos = self._historico[-10:]
        avg_fracao = sum(r["fracao"] for r in ultimos) / len(ultimos)
        avg_wr     = sum(r["winrate"] for r in ultimos) / len(ultimos)
        negativos  = sum(1 for r in ultimos if r["kelly_bruto"] <= 0)
        return (
            f"📐 <b>Kelly Criterion — Últimos {len(ultimos)} cálculos</b>\n"
            f"   Fração média: <b>{avg_fracao*100:.1f}%</b>\n"
            f"   Winrate médio: <b>{avg_wr:.1f}%</b>\n"
            f"   EV negativo: <b>{negativos}/{len(ultimos)}</b>\n"
            f"   Total histórico: <b>{len(self._historico)}</b> registros"
        )


# ══════════════════════════════════════════════════════════════════
# MÓDULO 2 — ExpectedValueCalc (Valor Esperado)
# Calcula EV de cada sinal antes de enviá-lo.
# Salva histórico em: expected_value.json
# ══════════════════════════════════════════════════════════════════

class ExpectedValueCalc:
    """
    EV = (p_win × lucro_líquido) - (p_loss × aposta)
    Para payout 2.0 e aposta de 1 unidade:
      EV = p × 1.0 - (1-p) × 1.0 = 2p - 1
    EV > 0 → entrada lucrativa a longo prazo
    EV < 0 → entrada com desvantagem matemática
    """
    DB_FILE = "expected_value.json"

    def __init__(self):
        self._historico: list = []
        self._load()

    def _load(self):
        if os.path.exists(self.DB_FILE):
            try:
                with open(self.DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._historico = data.get("historico", [])
                log.info(f"ExpectedValue: {len(self._historico)} registros carregados")
            except Exception as e:
                log.error(f"ExpectedValue load: {e}")

    def _save(self):
        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({"historico": self._historico[-500:]}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"ExpectedValue save: {e}")

    def calcular(self, wins: int, total: int, payout: float = 2.0,
                 aposta: float = 1.0, pattern_nome: str = "") -> dict:
        if total < 3:
            return {"ev": 0.0, "ev_pct": 0.0, "positivo": False,
                    "linha": "💹 EV: <i>dados insuficientes</i>"}
        p_win  = wins / total
        p_loss = 1.0 - p_win
        lucro_liquido = (payout - 1.0) * aposta
        ev = (p_win * lucro_liquido) - (p_loss * aposta)
        ev_pct = (ev / aposta) * 100 if aposta > 0 else 0.0
        positivo = ev > 0
        if ev > 0.15:
            emoji, texto = "🟢", "Excelente"
        elif ev > 0.05:
            emoji, texto = "🟡", "Positivo"
        elif ev > 0:
            emoji, texto = "🟠", "Marginalmente positivo"
        else:
            emoji, texto = "🔴", "NEGATIVO — não apostar"
        registro = {
            "hora": datetime.now().strftime("%H:%M:%S"),
            "pattern": pattern_nome,
            "wins": wins, "total": total,
            "p_win": round(p_win, 4),
            "payout": payout,
            "ev": round(ev, 4),
            "ev_pct": round(ev_pct, 2),
            "positivo": positivo,
        }
        self._historico.append(registro)
        self._save()
        return {
            "ev": round(ev, 4), "ev_pct": round(ev_pct, 2),
            "positivo": positivo, "p_win": round(p_win, 4),
            "linha": (
                f"💹 <b>EV</b> {emoji} <b>{ev:+.4f}</b> "
                f"(<b>{ev_pct:+.1f}%</b> por aposta)  "
                f"<i>p={p_win*100:.1f}% | {texto}</i>"
            ),
        }

    def ev_medio_historico(self) -> float:
        if not self._historico:
            return 0.0
        return sum(r["ev"] for r in self._historico) / len(self._historico)

    def resumo(self) -> str:
        if not self._historico:
            return "💹 <b>Expected Value</b>: sem dados ainda."
        positivos  = sum(1 for r in self._historico if r["positivo"])
        negativos  = len(self._historico) - positivos
        ev_medio   = self.ev_medio_historico()
        ultimos10  = self._historico[-10:]
        ev_recente = sum(r["ev"] for r in ultimos10) / len(ultimos10)
        return (
            f"💹 <b>Expected Value — Histórico</b>\n"
            f"   Total de cálculos: <b>{len(self._historico)}</b>\n"
            f"   EV positivo: <b>{positivos}</b> | negativo: <b>{negativos}</b>\n"
            f"   EV médio geral: <b>{ev_medio:+.4f}</b>\n"
            f"   EV médio últimos 10: <b>{ev_recente:+.4f}</b>"
        )


# ══════════════════════════════════════════════════════════════════
# MÓDULO 3 — ConfusionMatrix (F1-Score e Matriz de Confusão)
# Avalia desempenho real do bot com métricas precisas.
# Salva histórico em: confusion_matrix.json
# ══════════════════════════════════════════════════════════════════

class ConfusionMatrix:
    """
    Registra cada sinal e resultado para calcular:
      - Verdadeiro Positivo (VP): previu V/P → acertou
      - Falso Positivo (FP): previu V/P → errou
      - Precisão: VP / (VP + FP)
      - Recall: VP / (VP + FN)
      - F1-Score: 2 × (Precisão × Recall) / (Precisão + Recall)
    Salva tudo em confusion_matrix.json para análise offline.
    """
    DB_FILE = "confusion_matrix.json"

    def __init__(self):
        self._registros: list = []
        self._load()

    def _load(self):
        if os.path.exists(self.DB_FILE):
            try:
                with open(self.DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._registros = data.get("registros", [])
                log.info(f"ConfusionMatrix: {len(self._registros)} registros carregados")
            except Exception as e:
                log.error(f"ConfusionMatrix load: {e}")

    def _save(self):
        metricas = self._calcular_metricas()
        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "registros": self._registros[-1000:],
                    "metricas_atuais": metricas,
                    "ultima_atualizacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"ConfusionMatrix save: {e}")

    def registrar(self, predicao: str, resultado_real: str,
                  pattern_nome: str = "", score: float = 0.0) -> None:
        acerto = (predicao == resultado_real)
        self._registros.append({
            "hora": datetime.now().strftime("%H:%M:%S"),
            "predicao": predicao,
            "resultado_real": resultado_real,
            "acerto": acerto,
            "pattern": pattern_nome,
            "score": round(score, 1),
        })
        self._save()

    def _calcular_metricas(self) -> dict:
        if not self._registros:
            return {}
        for cor in ("V", "P"):
            pass
        # Métricas globais
        total   = len(self._registros)
        acertos = sum(1 for r in self._registros if r["acerto"])
        erros   = total - acertos
        # Por cor
        metricas_cor = {}
        for cor in ("V", "P"):
            previstos   = [r for r in self._registros if r["predicao"] == cor]
            tp = sum(1 for r in previstos if r["acerto"])
            fp = sum(1 for r in previstos if not r["acerto"])
            # FN = previu outra cor, resultado foi esta cor
            fn = sum(1 for r in self._registros
                     if r["predicao"] != cor and r["resultado_real"] == cor)
            precisao = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall   = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * precisao * recall / (precisao + recall)
                  if (precisao + recall) > 0 else 0.0)
            metricas_cor[cor] = {
                "tp": tp, "fp": fp, "fn": fn,
                "precisao": round(precisao, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "total_previstos": len(previstos),
            }
        return {
            "total": total, "acertos": acertos, "erros": erros,
            "accuracy": round(acertos / total, 4) if total > 0 else 0.0,
            "por_cor": metricas_cor,
        }

    def linha_status(self) -> str:
        m = self._calcular_metricas()
        if not m or m.get("total", 0) < 3:
            return "📊 F1: <i>coletando dados...</i>"
        pc = m.get("por_cor", {})
        f1_v = pc.get("V", {}).get("f1", 0)
        f1_p = pc.get("P", {}).get("f1", 0)
        acc  = m.get("accuracy", 0)
        return (
            f"📊 <b>F1</b>  🔴{f1_v:.2f}  ⚫{f1_p:.2f}  "
            f"| Acc <b>{acc*100:.1f}%</b> ({m['acertos']}✅/{m['erros']}❌)"
        )

    def resumo(self) -> str:
        m = self._calcular_metricas()
        if not m or m.get("total", 0) == 0:
            return "📊 <b>Matriz de Confusão</b>: sem dados ainda."
        pc = m.get("por_cor", {})
        mv = pc.get("V", {})
        mp = pc.get("P", {})
        return (
            f"📊 <b>Matriz de Confusão — F1-Score</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Total sinais: <b>{m['total']}</b> | "
            f"Accuracy: <b>{m['accuracy']*100:.1f}%</b>\n\n"
            f"🔴 <b>Vermelho</b>\n"
            f"   TP={mv.get('tp',0)} | FP={mv.get('fp',0)} | FN={mv.get('fn',0)}\n"
            f"   Precisão: <b>{mv.get('precisao',0)*100:.1f}%</b> | "
            f"Recall: <b>{mv.get('recall',0)*100:.1f}%</b> | "
            f"F1: <b>{mv.get('f1',0):.3f}</b>\n\n"
            f"⚫ <b>Preto</b>\n"
            f"   TP={mp.get('tp',0)} | FP={mp.get('fp',0)} | FN={mp.get('fn',0)}\n"
            f"   Precisão: <b>{mp.get('precisao',0)*100:.1f}%</b> | "
            f"Recall: <b>{mp.get('recall',0)*100:.1f}%</b> | "
            f"F1: <b>{mp.get('f1',0):.3f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )


# ══════════════════════════════════════════════════════════════════
# MÓDULO 4 — BootstrapValidator
# Valida se o winrate do minerador é real ou sorte estatística.
# Salva histórico em: bootstrap_validator.json
# ══════════════════════════════════════════════════════════════════

class BootstrapValidator:
    """
    Bootstrap (Reamostragem): cria N amostras aleatórias do histórico
    para estimar o intervalo de confiança real do winrate.
    Se o intervalo inferior ainda for >= limiar → padrão é estatisticamente válido.
    Se não → o 90% pode ser sorte (overfitting no histórico).
    """
    DB_FILE = "bootstrap_validator.json"
    N_AMOSTRAS = 500   # número de reamostras

    def __init__(self):
        self._validacoes: list = []
        self._load()

    def _load(self):
        if os.path.exists(self.DB_FILE):
            try:
                with open(self.DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._validacoes = data.get("validacoes", [])
                log.info(f"Bootstrap: {len(self._validacoes)} validações carregadas")
            except Exception as e:
                log.error(f"Bootstrap load: {e}")

    def _save(self):
        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "validacoes": self._validacoes[-200:],
                    "ultima_atualizacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"Bootstrap save: {e}")

    def validar(self, wins: int, total: int, limiar: float = 0.90,
                pattern_nome: str = "") -> dict:
        """
        Retorna intervalo de confiança 95% para o winrate via bootstrap.
        wins/total = resultados reais observados.
        """
        if total < 5:
            return {
                "valido": None, "ic_inferior": 0.0, "ic_superior": 0.0,
                "winrate_obs": 0.0, "n_amostras": 0,
                "linha": "🔬 Bootstrap: <i>mín. 5 amostras necessárias</i>",
            }
        import random
        dados = [1] * wins + [0] * (total - wins)
        medias = []
        for _ in range(self.N_AMOSTRAS):
            amostra = [random.choice(dados) for _ in range(total)]
            medias.append(sum(amostra) / total)
        medias.sort()
        ic_inf = medias[int(0.025 * self.N_AMOSTRAS)]
        ic_sup = medias[int(0.975 * self.N_AMOSTRAS)]
        wr_obs = wins / total
        valido = ic_inf >= limiar * 0.85   # IC inferior >= 85% do limiar exigido
        if valido and ic_inf >= limiar:
            emoji, texto = "🟢", "VÁLIDO — padrão robusto"
        elif valido:
            emoji, texto = "🟡", "PROVÁVEL — margem aceitável"
        else:
            emoji, texto = "🔴", "SUSPEITO — pode ser sorte"
        registro = {
            "hora": datetime.now().strftime("%H:%M:%S"),
            "pattern": pattern_nome,
            "wins": wins, "total": total,
            "winrate_obs": round(wr_obs, 4),
            "ic_inferior": round(ic_inf, 4),
            "ic_superior": round(ic_sup, 4),
            "limiar": limiar,
            "valido": valido,
        }
        self._validacoes.append(registro)
        self._save()
        return {
            "valido": valido, "ic_inferior": round(ic_inf, 4),
            "ic_superior": round(ic_sup, 4), "winrate_obs": round(wr_obs, 4),
            "n_amostras": self.N_AMOSTRAS,
            "linha": (
                f"🔬 <b>Bootstrap</b> {emoji} IC95% "
                f"[<b>{ic_inf*100:.1f}%</b> — <b>{ic_sup*100:.1f}%</b>]  "
                f"obs={wr_obs*100:.1f}%  <i>{texto}</i>"
            ),
        }

    def resumo(self) -> str:
        if not self._validacoes:
            return "🔬 <b>Bootstrap Validator</b>: sem validações ainda."
        validos   = sum(1 for v in self._validacoes if v.get("valido"))
        suspeitos = len(self._validacoes) - validos
        ic_medio  = sum(v["ic_inferior"] for v in self._validacoes) / len(self._validacoes)
        return (
            f"🔬 <b>Bootstrap Validator</b>\n"
            f"   Total validações: <b>{len(self._validacoes)}</b>\n"
            f"   Padrões válidos: <b>{validos}</b> | Suspeitos: <b>{suspeitos}</b>\n"
            f"   IC inferior médio: <b>{ic_medio*100:.1f}%</b>\n"
            f"   Reamostras por validação: <b>{self.N_AMOSTRAS}</b>"
        )


# ══════════════════════════════════════════════════════════════════
# SIMULADOR DE GALE 2
# Mesmo com max_gale=1, simula o que teria acontecido se tivesse
# usado gale 2. Mostra no sinal e salva estatísticas em JSON.
# ══════════════════════════════════════════════════════════════════

class SimulacaoGale:
    """
    Quando o bot opera com max_gale=1, simula o resultado do gale 2
    e acumula estatísticas históricas salvas em sim_gale2_stats.json.

    Campos por entrada:
      - prediction : cor apostada
      - gale1_cor  : cor que saiu no gale 1 (ativou o gale 2?)
      - gale2_cor  : cor que saiu no gale 2 (simulado)
      - resultado  : WIN_G1 | WIN_G2_SIM | LOSS_G2_SIM
      - hora       : HH:MM:SS
      - padrao     : nome do padrão
    """

    DB_FILE = "sim_gale2_stats.json"

    def __init__(self):
        self._historico: list = []
        self._pendente:  dict = {}   # sinal aguardando resolução do gale 2
        self._load()

    def _load(self):
        if not os.path.exists(self.DB_FILE):
            return
        try:
            with open(self.DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._historico = data.get("historico", [])
        except Exception as e:
            log.warning(f"SimulacaoGale load: {e}")

    def _save(self):
        try:
            wins_g1  = sum(1 for e in self._historico if e["resultado"] == "WIN_G1")
            wins_g2  = sum(1 for e in self._historico if e["resultado"] == "WIN_G2_SIM")
            losses   = sum(1 for e in self._historico if e["resultado"] == "LOSS_G2_SIM")
            total    = len(self._historico)
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "historico":   self._historico[-500:],
                    "resumo": {
                        "total":    total,
                        "win_g1":   wins_g1,
                        "win_g2":   wins_g2,
                        "loss_g2":  losses,
                        "acc_g1":   round(wins_g1 / max(1, total) * 100, 1),
                        "acc_g1_g2":round((wins_g1 + wins_g2) / max(1, total) * 100, 1),
                    },
                    "ultima_atualizacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning(f"SimulacaoGale save: {e}")

    def iniciar_sinal(self, prediction: str, padrao_nome: str) -> None:
        """Registra o início de um sinal para monitorar o gale 2."""
        self._pendente = {
            "prediction":  prediction,
            "padrao_nome": padrao_nome,
            "hora":        datetime.now().strftime("%H:%M:%S"),
            "gale1_cor":   None,
            "gale2_cor":   None,
            "resultado":   None,
        }

    def registrar_gale1(self, cor_saiu: str) -> None:
        """Registra a cor que saiu no gale 1 (bot vai para gale 2 simulado)."""
        if self._pendente:
            self._pendente["gale1_cor"] = cor_saiu

    def registrar_win_direto(self) -> None:
        """WIN antes do gale — não precisa simular."""
        self._pendente = {}

    def registrar_gale2_simulado(self, cor_gale2: str) -> str:
        """
        Registra o resultado do gale 2 simulado (rodada seguinte ao gale 1).
        Retorna a string de resultado para exibir no Telegram.
        """
        if not self._pendente or not self._pendente.get("gale1_cor"):
            return ""

        pred = self._pendente["prediction"]
        g2   = cor_gale2

        if g2 == pred:
            resultado = "WIN_G2_SIM"
            emoji_res = "✅ <b>WIN simulado no Gale 2</b>"
        else:
            resultado = "LOSS_G2_SIM"
            emoji_res = "❌ <b>LOSS mesmo no Gale 2</b>"

        self._pendente["gale2_cor"] = g2
        self._pendente["resultado"] = resultado
        self._historico.append(dict(self._pendente))
        self._pendente = {}
        self._save()

        # Linha para exibir no WIN/LOSS message
        CE = {"V": "🔴", "P": "⚫", "B": "⚪"}
        g1_e = CE.get(self._pendente.get("gale1_cor", ""), "?")  # já limpo, usa dict antes
        g2_e = CE.get(g2, "?")
        return (
            f"🔮 <b>Simulação Gale 2</b>: saiu {g2_e}  →  {emoji_res}\n"
        )

    def resumo(self) -> str:
        """Relatório completo para comando /simgale."""
        if not self._historico:
            return "📊 <b>Simulação Gale 2</b>: sem dados ainda."

        total   = len(self._historico)
        wins_g1 = sum(1 for e in self._historico if e["resultado"] == "WIN_G1")
        wins_g2 = sum(1 for e in self._historico if e["resultado"] == "WIN_G2_SIM")
        losses  = sum(1 for e in self._historico if e["resultado"] == "LOSS_G2_SIM")

        acc_g1    = round(wins_g1 / max(1, total) * 100, 1)
        acc_g1g2  = round((wins_g1 + wins_g2) / max(1, total) * 100, 1)

        # Últimas 10 entradas
        CE = {"V": "🔴", "P": "⚫", "B": "⚪"}
        linhas = []
        for e in self._historico[-10:]:
            pred = CE.get(e.get("prediction",""), "?")
            g1   = CE.get(e.get("gale1_cor",""), "?")
            g2   = CE.get(e.get("gale2_cor",""), "?")
            if e["resultado"] == "WIN_G2_SIM":
                res = "✅ WIN G2"
            else:
                res = "❌ LOSS G2"
            linhas.append(
                f"  {e['hora']}  [{e.get('padrao_nome','?')}]  "
                f"prev:{pred} g1:{g1} g2:{g2}  {res}"
            )

        return (
            f"🔮 <b>Simulação Gale 2</b> (max_gale=1)\n"
            f"{'─' * 22}\n"
            f"Total de entradas: <b>{total}</b>\n\n"
            f"✅ Win no Gale 1: <b>{wins_g1}</b> ({acc_g1}%)\n"
            f"✅ Win no Gale 2 (sim): <b>{wins_g2}</b>\n"
            f"❌ Loss mesmo no G2: <b>{losses}</b>\n\n"
            f"📊 Acc com G1 só: <b>{acc_g1}%</b>\n"
            f"📊 Acc com G1+G2: <b>{acc_g1g2}%</b>\n"
            f"💡 Ganho com G2: <b>+{round(acc_g1g2 - acc_g1, 1)}%</b>\n"
            f"{'─' * 22}\n"
            f"<b>Últimas 10:</b>\n"
            + "\n".join(linhas)
        )





# ══════════════════════════════════════════════════════════════════
# MÓDULO — MenteViva
# Motor de inteligência que aprende a cada rodada e emite veredito
# fundamentado a cada sinal. Aprende com wins, losses, clusters,
# momentum, hora, score, seca, regime. Salva em mente_viva.json.
# ══════════════════════════════════════════════════════════════════

class MenteViva:
    DB_FILE       = "mente_viva.json"
    JANELA_MOMENT = 20   # últimas N entradas para momentum recente
    JANELA_CLUSTER= 10   # janela para detectar cluster de losses
    MIN_AMOSTRAS  = 15   # mín para conclusões confiáveis por dimensão

    def __init__(self):
        self._mem = self._estrutura_vazia()
        self._load()
        # Se nunca foi populada, aprende com confusion_matrix existente
        if self._mem["meta"]["total_entradas"] == 0:
            self._pre_popular_historico()
        tot = self._mem["meta"]["total_entradas"]
        log.info(f"MenteViva: carregada | {tot} entradas aprendidas")

    # ──────────────────────────────────────────────────────────────
    # ESTRUTURA DE MEMÓRIA
    # ──────────────────────────────────────────────────────────────

    def _estrutura_vazia(self) -> dict:
        from datetime import datetime
        return {
            "meta": {
                "criado":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_entradas": 0,
                "total_wins":     0,
                "total_losses":   0,
                "versao":         "2.0"
            },
            "por_hora": {
                str(h): {"wins": 0, "losses": 0, "winrate": 0.0}
                for h in range(24)
            },
            "por_score": {
                "95-100": {"wins": 0, "losses": 0, "winrate": 0.0},
                "90-94":  {"wins": 0, "losses": 0, "winrate": 0.0},
                "85-89":  {"wins": 0, "losses": 0, "winrate": 0.0},
                "80-84":  {"wins": 0, "losses": 0, "winrate": 0.0},
                "lt80":   {"wins": 0, "losses": 0, "winrate": 0.0}
            },
            "por_predicao": {
                "V": {"wins": 0, "losses": 0, "winrate": 0.0},
                "P": {"wins": 0, "losses": 0, "winrate": 0.0}
            },
            "seca_no_sinal": {
                "V": {"wins": [], "losses": [], "media_win": 0.0, "media_loss": 0.0,
                      "distribuicao_wins": {}, "maximo_win": 0},
                "P": {"wins": [], "losses": [], "media_win": 0.0, "media_loss": 0.0,
                      "distribuicao_wins": {}, "maximo_win": 0},
                "B": {"wins": [], "losses": [], "media_win": 0.0, "media_loss": 0.0,
                      "distribuicao_wins": {}, "maximo_win": 0}
            },
            "pos_loss": {
                "apos_1_loss": {"wins": 0, "total": 0, "winrate": 0.0},
                "apos_2_loss": {"wins": 0, "total": 0, "winrate": 0.0},
                "apos_3_loss": {"wins": 0, "total": 0, "winrate": 0.0}
            },
            "pos_win_streak": {
                "apos_3+": {"wins": 0, "total": 0, "winrate": 0.0},
                "apos_7+": {"wins": 0, "total": 0, "winrate": 0.0},
                "apos_15+":{"wins": 0, "total": 0, "winrate": 0.0}
            },
            "por_regime": {
                "trending":    {"wins": 0, "losses": 0, "winrate": 0.0},
                "alternating": {"wins": 0, "losses": 0, "winrate": 0.0},
                "chaotic":     {"wins": 0, "losses": 0, "winrate": 0.0}
            },
            "momentum_recente": [],   # lista de True/False (últimas 20)
            "ultimos_50": [],         # registros detalhados
            "padroes_notaveis": {
                "melhor_hora":   {"hora": "", "winrate": 0.0},
                "pior_hora":     {"hora": "", "winrate": 1.0},
                "score_critico": 85.0,
                "seca_ideal_V":  0.0,
                "seca_ideal_P":  0.0
            },
            "conclusoes_aprendidas": [],
            "entropia": {
                "historico_h": [], "media_h": 0.0, "h_maximo": 0.0, "h_minimo": 1.0,
                "wins_por_faixa_h": {
                    "baixa_0_07":  {"wins":0,"total":0,"winrate":0.0},
                    "media_07_09": {"wins":0,"total":0,"winrate":0.0},
                    "alta_09_099": {"wins":0,"total":0,"winrate":0.0},
                    "maxima_1":    {"wins":0,"total":0,"winrate":0.0}
                },
                "amostras": 0
            },
            "markov": {
                "transicoes": {
                    "V→V":{"count":0,"prob":0.0},"V→P":{"count":0,"prob":0.0},"V→B":{"count":0,"prob":0.0},
                    "P→V":{"count":0,"prob":0.0},"P→P":{"count":0,"prob":0.0},"P→B":{"count":0,"prob":0.0},
                    "B→V":{"count":0,"prob":0.0},"B→P":{"count":0,"prob":0.0},"B→B":{"count":0,"prob":0.0}
                },
                "sequencias_3": {}, "amostras": 0, "insight_atual": ""
            },
            "calibracao": {
                "por_veredito": {
                    "EXCELENTE":       {"wins":0,"total":0,"winrate":0.0,"brier_sum":0.0},
                    "MUITO FAVORAVEL": {"wins":0,"total":0,"winrate":0.0,"brier_sum":0.0},
                    "FAVORAVEL":       {"wins":0,"total":0,"winrate":0.0,"brier_sum":0.0},
                    "NEUTRO":          {"wins":0,"total":0,"winrate":0.0,"brier_sum":0.0},
                    "CAUTELA":         {"wins":0,"total":0,"winrate":0.0,"brier_sum":0.0},
                    "DESFAVORAVEL":    {"wins":0,"total":0,"winrate":0.0,"brier_sum":0.0}
                },
                "brier_global": 0.0, "amostras": 0
            },
            "fingerprint_loss": {
                "score_medio_loss": 0.0, "hora_mais_losses": {}, "regime_mais_losses": {},
                "seca_pred_media_loss": 0.0, "seca_pred_media_win": 0.0,
                "losses_apos_branco": 0, "total_losses_analisados": 0
            },
            "pressao_acumulada": {
                "V": {"pressao_atual":0.0,"historico_pressao_no_win":[],"media_pressao_win":0.0,"pressao_critica":0.0},
                "P": {"pressao_atual":0.0,"historico_pressao_no_win":[],"media_pressao_win":0.0,"pressao_critica":0.0}
            },
            "score_hora_combo": {},
            "seca_combo": {
                "wins": {}, "losses": {},
                "risco_combos": []
            },
            "velocidade_mercado": {
                "timestamps_sinais": [],
                "por_velocidade": {
                    "lento_5+min":  {"wins":0,"total":0,"winrate":0.0},
                    "normal_1_5min":{"wins":0,"total":0,"winrate":0.0},
                    "rapido_lt1min":{"wins":0,"total":0,"winrate":0.0}
                }
            },
            "padrao_pre_loss": {
                "sequencias": {},
                "top_perdedoras": []
            },
            "fadiga_padrao": {},
            "mudanca_comportamento": {
                "historico_wr_janela": [],
                "alerta_ativo": False,
                "ultimo_alerta": "",
                "nivel": "normal"
            }
        }

    def _pre_popular_historico(self):
        """
        Na primeira execução, aprende com os dados do confusion_matrix.json
        e sequencia_seco.json já existentes — MenteViva não nasce do zero.
        """
        import os
        CM_FILE  = "confusion_matrix.json"
        SEQ_FILE = "sequencia_seco.json"
        if not (os.path.exists(CM_FILE) and os.path.exists(SEQ_FILE)):
            log.info("MenteViva: arquivos históricos não encontrados — iniciando do zero")
            return
        try:
            with open(CM_FILE, "r", encoding="utf-8") as f:
                cm = json.load(f)
            with open(SEQ_FILE, "r", encoding="utf-8") as f:
                seq = json.load(f)
            regs = cm.get("registros", [])
            hist = seq.get("hist", [])
            if not regs or not hist:
                return

            streak_w = 0
            streak_l = 0
            total = len(regs)

            for i, reg in enumerate(regs):
                # Posição aproximada no histórico de cores
                pos = max(1, int(i * len(hist) / total))
                pos = min(pos, len(hist))

                # Reconstrói seca de cada cor até esse ponto
                def _seca_em(cor, p=pos):
                    seca = 0
                    for c in reversed(hist[:p]):
                        if c == cor: break
                        seca += 1
                    return seca

                win   = reg["acerto"]
                score = reg.get("score", 85.0)
                hora  = reg.get("hora", "00:00:00")
                pred  = reg.get("predicao", "P")
                h     = hora[:2]
                fsc   = self._faixa_score(score)

                # Atualiza por_hora
                ph = self._mem["por_hora"][h]
                if win: ph["wins"]   += 1
                else:   ph["losses"] += 1
                t = ph["wins"] + ph["losses"]
                ph["winrate"] = round(ph["wins"] / t, 4)

                # Atualiza por_score
                ps = self._mem["por_score"][fsc]
                if win: ps["wins"]   += 1
                else:   ps["losses"] += 1
                t = ps["wins"] + ps["losses"]
                ps["winrate"] = round(ps["wins"] / t, 4)

                # Atualiza por_predicao
                pp = self._mem["por_predicao"][pred]
                if win: pp["wins"]   += 1
                else:   pp["losses"] += 1
                t = pp["wins"] + pp["losses"]
                pp["winrate"] = round(pp["wins"] / t, 4)

                # Atualiza seca_no_sinal
                MAX_H = 300
                for cor_k, seca_val in [("V", _seca_em("V")), ("P", _seca_em("P")), ("B", _seca_em("B"))]:
                    bloco = self._mem["seca_no_sinal"][cor_k]
                    lista = "wins" if win else "losses"
                    bloco[lista].append(seca_val)
                    if len(bloco[lista]) > MAX_H:
                        bloco[lista] = bloco[lista][-MAX_H:]
                    if bloco["wins"]:
                        bloco["media_win"]  = round(sum(bloco["wins"]) / len(bloco["wins"]), 2)
                        bloco["maximo_win"] = max(bloco["wins"])
                        dist = {}
                        for sv in bloco["wins"]:
                            k2 = str(sv)
                            dist[k2] = dist.get(k2, 0) + 1
                        bloco["distribuicao_wins"] = dist
                    if bloco["losses"]:
                        bloco["media_loss"] = round(sum(bloco["losses"]) / len(bloco["losses"]), 2)

                # Atualiza pos_loss
                if streak_l >= 1:
                    chave = f"apos_{min(streak_l,3)}_loss"
                    if chave in self._mem["pos_loss"]:
                        pl = self._mem["pos_loss"][chave]
                        pl["total"] += 1
                        if win: pl["wins"] += 1
                        pl["winrate"] = round(pl["wins"] / pl["total"], 4)

                # Atualiza pos_win_streak
                for threshold, chave in [(3,"apos_3+"), (7,"apos_7+"), (15,"apos_15+")]:
                    if streak_w >= threshold:
                        pw = self._mem["pos_win_streak"][chave]
                        pw["total"] += 1
                        if win: pw["wins"] += 1
                        pw["winrate"] = round(pw["wins"] / pw["total"], 4)

                # Atualiza momentum e meta
                self._mem["momentum_recente"].append(win)
                if len(self._mem["momentum_recente"]) > self.JANELA_MOMENT:
                    self._mem["momentum_recente"] = self._mem["momentum_recente"][-self.JANELA_MOMENT:]
                self._mem["meta"]["total_entradas"] += 1
                if win: self._mem["meta"]["total_wins"]   += 1
                else:   self._mem["meta"]["total_losses"] += 1

                # Atualiza streaks para próxima iteração
                if win: streak_w += 1; streak_l = 0
                else:   streak_l += 1; streak_w = 0

            self._atualizar_padroes_notaveis()
            self._save()
            log.info(
                f"MenteViva: pré-populada com {total} entradas históricas | "
                f"{self._mem['meta']['total_wins']}W {self._mem['meta']['total_losses']}L"
            )
        except Exception as e:
            log.error(f"MenteViva pré-popular: {e}")

    def _load(self):
        import os
        try:
            if os.path.exists(self.DB_FILE):
                with open(self.DB_FILE, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                # Merge com estrutura vazia para compatibilidade
                base = self._estrutura_vazia()
                for k in dados:
                    if k in base:
                        base[k] = dados[k]
                self._mem = base
        except Exception as e:
            log.error(f"MenteViva load: {e}")

    def _save(self):
        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump(self._mem, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"MenteViva save: {e}")

    # ──────────────────────────────────────────────────────────────
    # APRENDIZADO — chamado após cada resultado
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _calcular_seca(history: list, cor: str) -> int:
        seca = 0
        for c in reversed(history):
            if c == cor: break
            seca += 1
        return seca

    @staticmethod
    def _faixa_score(score: float) -> str:
        if score >= 95: return "95-100"
        if score >= 90: return "90-94"
        if score >= 85: return "85-89"
        if score >= 80: return "80-84"
        return "lt80"

    def aprender(
        self,
        win: bool,
        score: float,
        hora: str,          # "HH:MM:SS"
        predicao: str,      # "V" ou "P"
        history: list,      # history_buffer no momento
        regime: str,
        loss_streak_antes: int,
        win_streak_antes:  int,
        nome_padrao: str = "",
    ):
        """Registra resultado e atualiza toda a memória."""
        from datetime import datetime

        seca_v = self._calcular_seca(history, "V")
        seca_p = self._calcular_seca(history, "P")
        seca_b = self._calcular_seca(history, "B")
        h      = hora[:2]
        fsc    = self._faixa_score(score)

        # ── Meta ──────────────────────────────────────────────────
        self._mem["meta"]["total_entradas"] += 1
        if win: self._mem["meta"]["total_wins"]   += 1
        else:   self._mem["meta"]["total_losses"] += 1

        # ── Por hora ──────────────────────────────────────────────
        ph = self._mem["por_hora"][h]
        if win: ph["wins"]   += 1
        else:   ph["losses"] += 1
        t = ph["wins"] + ph["losses"]
        ph["winrate"] = round(ph["wins"] / t, 4) if t else 0.0

        # ── Por score ─────────────────────────────────────────────
        ps = self._mem["por_score"][fsc]
        if win: ps["wins"]   += 1
        else:   ps["losses"] += 1
        t = ps["wins"] + ps["losses"]
        ps["winrate"] = round(ps["wins"] / t, 4) if t else 0.0

        # ── Por predição ──────────────────────────────────────────
        pp = self._mem["por_predicao"][predicao]
        if win: pp["wins"]   += 1
        else:   pp["losses"] += 1
        t = pp["wins"] + pp["losses"]
        pp["winrate"] = round(pp["wins"] / t, 4) if t else 0.0

        # ── Seca no momento do sinal ──────────────────────────────
        MAX_HIST_SECA = 300
        for cor_key, seca_val in [("V", seca_v), ("P", seca_p), ("B", seca_b)]:
            bloco = self._mem["seca_no_sinal"][cor_key]
            lista = "wins" if win else "losses"
            bloco[lista].append(seca_val)
            if len(bloco[lista]) > MAX_HIST_SECA:
                bloco[lista] = bloco[lista][-MAX_HIST_SECA:]
            if bloco["wins"]:
                bloco["media_win"]  = round(sum(bloco["wins"]) / len(bloco["wins"]), 2)
                bloco["maximo_win"] = max(bloco["wins"])
                dist = {}
                for sv in bloco["wins"]:
                    k = str(sv)
                    dist[k] = dist.get(k, 0) + 1
                bloco["distribuicao_wins"] = dist
            if bloco["losses"]:
                bloco["media_loss"] = round(sum(bloco["losses"]) / len(bloco["losses"]), 2)

        # ── Pós-loss ──────────────────────────────────────────────
        if loss_streak_antes >= 1:
            chave = f"apos_{min(loss_streak_antes,3)}_loss"
            if chave in self._mem["pos_loss"]:
                pl = self._mem["pos_loss"][chave]
                pl["total"] += 1
                if win: pl["wins"] += 1
                pl["winrate"] = round(pl["wins"] / pl["total"], 4) if pl["total"] else 0.0

        # ── Pós-win-streak ────────────────────────────────────────
        for threshold, chave in [(3,"apos_3+"), (7,"apos_7+"), (15,"apos_15+")]:
            if win_streak_antes >= threshold:
                pw = self._mem["pos_win_streak"][chave]
                pw["total"] += 1
                if win: pw["wins"] += 1
                pw["winrate"] = round(pw["wins"] / pw["total"], 4) if pw["total"] else 0.0

        # ── Por regime ────────────────────────────────────────────
        if regime in self._mem["por_regime"]:
            pr = self._mem["por_regime"][regime]
            if win: pr["wins"]   += 1
            else:   pr["losses"] += 1
            t = pr["wins"] + pr["losses"]
            pr["winrate"] = round(pr["wins"] / t, 4) if t else 0.0

        # ── Momentum ─────────────────────────────────────────────
        self._mem["momentum_recente"].append(win)
        if len(self._mem["momentum_recente"]) > self.JANELA_MOMENT:
            self._mem["momentum_recente"] = self._mem["momentum_recente"][-self.JANELA_MOMENT:]

        # ── Últimos 50 ───────────────────────────────────────────
        reg = {
            "ts":        datetime.now().strftime("%H:%M:%S"),
            "win":       win,
            "score":     round(score, 1),
            "hora":      h,
            "predicao":  predicao,
            "seca_v":    seca_v,
            "seca_p":    seca_p,
            "seca_b":    seca_b,
            "regime":    regime,
            "loss_antes": loss_streak_antes,
            "win_antes":  win_streak_antes
        }
        self._mem["ultimos_50"].append(reg)
        if len(self._mem["ultimos_50"]) > 50:
            self._mem["ultimos_50"] = self._mem["ultimos_50"][-50:]

        # ── Padrões notáveis ─────────────────────────────────────
        self._atualizar_padroes_notaveis()

        # ── Entropia ─────────────────────────────────────────────
        self._atualizar_entropia(history, win)

        # ── Markov ───────────────────────────────────────────────
        self._atualizar_markov(history)

        # ── Fingerprint de perda ──────────────────────────────────
        self._atualizar_fingerprint(win, score, h, predicao, seca_v, seca_p, regime)

        # ── Pressão acumulada ─────────────────────────────────────
        self._atualizar_pressao(history, win, predicao)

        # ── 10 módulos extras ─────────────────────────────────────
        self._atualizar_10modulos(
            win=win, score=score, hora=hora, predicao=predicao,
            seca_v=seca_v, seca_p=seca_p,
            win_streak_antes=win_streak_antes,
            history=history
        )

        # ── Score+Hora combinados ─────────────────────────────────
        self._atualizar_score_hora(win, score, h)

        # ── Seca combo V+P ────────────────────────────────────────
        self._atualizar_seca_combo(win, seca_v, seca_p)

        # ── Velocidade do mercado ─────────────────────────────────
        self._atualizar_velocidade(win, hora)

        # ── Padrão pré-loss ───────────────────────────────────────
        self._atualizar_padrao_pre_loss(win, history)

        # ── Fadiga do padrão ──────────────────────────────────────
        self._atualizar_fadiga(win, nome_padrao if hasattr(self, "_nome_padrao_atual") else "")

        # ── Mudança brusca de comportamento ──────────────────────
        self._detectar_mudanca_comportamento(win)

        # ── Gera conclusões ──────────────────────────────────────
        self._gerar_conclusoes(win, score, h, predicao, seca_v, seca_p, regime,
                                loss_streak_antes, win_streak_antes)

        self._save()

    def _atualizar_padroes_notaveis(self):
        pn = self._mem["padroes_notaveis"]

        # Melhor/pior hora
        horas_validas = [
            (h, d) for h, d in self._mem["por_hora"].items()
            if d["wins"] + d["losses"] >= self.MIN_AMOSTRAS
        ]
        if horas_validas:
            melhor = max(horas_validas, key=lambda x: x[1]["winrate"])
            pior   = min(horas_validas, key=lambda x: x[1]["winrate"])
            pn["melhor_hora"] = {"hora": melhor[0], "winrate": round(melhor[1]["winrate"]*100,1)}
            pn["pior_hora"]   = {"hora": pior[0],   "winrate": round(pior[1]["winrate"]*100,1)}

        # Score crítico: menor faixa com winrate >= 80%
        for faixa in ["95-100","90-94","85-89","80-84","lt80"]:
            d = self._mem["por_score"][faixa]
            if d["wins"]+d["losses"] >= self.MIN_AMOSTRAS and d["winrate"] < 0.75:
                limites = {"95-100":95,"90-94":90,"85-89":85,"80-84":80,"lt80":75}
                pn["score_critico"] = limites[faixa]
                break

        # Seca ideal V e P
        sv = self._mem["seca_no_sinal"]["V"]
        sp = self._mem["seca_no_sinal"]["P"]
        if sv["wins"]:
            pn["seca_ideal_V"] = sv["media_win"]
        if sp["wins"]:
            pn["seca_ideal_P"] = sp["media_win"]



    # ──────────────────────────────────────────────────────────────
    # MÓDULOS EXTRAS — 10 dimensões adicionais
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _periodo_dia(hora: str) -> str:
        hi = int(hora[:2])
        if 6 <= hi < 12:  return "manha_06_12"
        if 12 <= hi < 18: return "tarde_12_18"
        if 18 <= hi < 24: return "noite_18_00"
        return "madrugada_00_06"

    @staticmethod
    def _faixa_streak(ws: int) -> str:
        if ws == 0:    return "0"
        if ws <= 3:    return "1-3"
        if ws <= 7:    return "4-7"
        if ws <= 14:   return "8-14"
        return "15+"

    def _atualizar_10modulos(
        self, win: bool, score: float, hora: str,
        predicao: str, seca_v: int, seca_p: int,
        win_streak_antes: int, history: list,
        nome_padrao: str = ""
    ):
        """Atualiza os 10 módulos extras a cada resultado."""
        import time as _time
        from datetime import datetime

        # ── 1. Score + Hora ───────────────────────────────────────
        sh = self._mem.get("score_hora", {"dados":{},"amostras":0})
        sc = score
        if sc >= 95: fsc = "95+"
        elif sc >= 90: fsc = "90-94"
        elif sc >= 85: fsc = "85-89"
        else: fsc = "lt85"
        chave_sh = f"{hora[:2]}h_{fsc}"
        if chave_sh not in sh["dados"]:
            sh["dados"][chave_sh] = {"wins":0,"losses":0,"winrate":0.0}
        b = sh["dados"][chave_sh]
        if win: b["wins"] += 1
        else:   b["losses"] += 1
        t = b["wins"]+b["losses"]
        b["winrate"] = round(b["wins"]/t, 4)
        sh["amostras"] = sh.get("amostras",0) + 1
        self._mem["score_hora"] = sh

        # ── 2. Seca dupla V+P ─────────────────────────────────────
        sd = self._mem.get("seca_dupla", {"dados":{},"perfil_win":[],"perfil_loss":[],"amostras":0})
        sv_c = min(seca_v,9); sp_c = min(seca_p,9)
        fv = "0" if sv_c==0 else "1-2" if sv_c<=2 else "3-5" if sv_c<=5 else "6+"
        fp = "0" if sp_c==0 else "1-2" if sp_c<=2 else "3-5" if sp_c<=5 else "6+"
        chave_sd = f"V{fv}_P{fp}"
        if chave_sd not in sd["dados"]:
            sd["dados"][chave_sd] = {"wins":0,"losses":0,"winrate":0.0}
        b2 = sd["dados"][chave_sd]
        if win:
            b2["wins"] += 1
            sd["perfil_win"].append([seca_v, seca_p])
            if len(sd["perfil_win"]) > 100: sd["perfil_win"] = sd["perfil_win"][-100:]
        else:
            b2["losses"] += 1
            sd["perfil_loss"].append([seca_v, seca_p])
            if len(sd["perfil_loss"]) > 100: sd["perfil_loss"] = sd["perfil_loss"][-100:]
        t2 = b2["wins"]+b2["losses"]
        b2["winrate"] = round(b2["wins"]/t2, 4)
        sd["amostras"] = sd.get("amostras",0) + 1
        self._mem["seca_dupla"] = sd

        # ── 3. Velocidade do mercado ──────────────────────────────
        vm = self._mem.get("velocidade_mercado", {})
        if vm:
            now_ts = datetime.now().strftime("%H:%M:%S")
            ts_list = vm.get("timestamps_sinais", [])
            ts_list.append(now_ts)
            # Manter só última hora
            if len(ts_list) > 120: ts_list = ts_list[-120:]
            vm["timestamps_sinais"] = ts_list
            # Conta sinais na última hora (aprox.: últimos 60 registros = ~1h)
            vel = len(ts_list)
            if vel <= 3:   fvel = "lento_0_3"
            elif vel <= 8: fvel = "normal_4_8"
            elif vel <= 15:fvel = "rapido_9_15"
            else:          fvel = "acelerado_15+"
            bv = vm.get(fvel, {"wins":0,"losses":0,"winrate":0.0})
            if win: bv["wins"] += 1
            else:   bv["losses"] += 1
            tv = bv["wins"]+bv["losses"]
            bv["winrate"] = round(bv["wins"]/tv, 4)
            vm[fvel] = bv
            vm["amostras"] = vm.get("amostras",0) + 1
            self._mem["velocidade_mercado"] = vm

        # ── 4. Padrão pré-loss ────────────────────────────────────
        ppl = self._mem.get("padrao_pre_loss", {})
        if ppl and history:
            vp_hist = [c for c in history if c in ("V","P")][-5:]
            if len(vp_hist) == 5:
                seq5 = "".join(vp_hist)
                seqs = ppl.get("sequencias", {})
                if seq5 not in seqs:
                    seqs[seq5] = {"count_loss":0,"count_win":0,"taxa_loss":0.0}
                if win:
                    seqs[seq5]["count_win"] += 1
                    ppl["amostras_win"] = ppl.get("amostras_win",0) + 1
                else:
                    seqs[seq5]["count_loss"] += 1
                    ppl["amostras_loss"] = ppl.get("amostras_loss",0) + 1
                total_seq = seqs[seq5]["count_loss"] + seqs[seq5]["count_win"]
                seqs[seq5]["taxa_loss"] = round(seqs[seq5]["count_loss"]/total_seq, 4)
                # Manter top 30
                if len(seqs) > 30:
                    menor = min(seqs.items(),
                                key=lambda x: x[1]["count_loss"]+x[1]["count_win"])
                    del seqs[menor[0]]
                ppl["sequencias"] = seqs
                # Top perigosas (taxa_loss >= 0.5 com >= 3 amostras)
                perigosas = sorted(
                    [(k,v) for k,v in seqs.items()
                     if v["count_loss"]+v["count_win"]>=3 and v["taxa_loss"]>=0.5],
                    key=lambda x: x[1]["taxa_loss"], reverse=True
                )[:5]
                ppl["top_perigosas"] = [
                    {"seq":k,"taxa_loss":v["taxa_loss"],
                     "count_loss":v["count_loss"],"total":v["count_loss"]+v["count_win"]}
                    for k,v in perigosas
                ]
                self._mem["padrao_pre_loss"] = ppl

        # ── 5. Fadiga do padrão ───────────────────────────────────
        fp_m = self._mem.get("fadiga_padrao", {})
        if fp_m:
            fk = self._faixa_streak(win_streak_antes)
            bfp = fp_m["por_streak"].get(fk, {"wins":0,"losses":0,"winrate":0.0})
            if win: bfp["wins"] += 1
            else:   bfp["losses"] += 1
            tfp = bfp["wins"]+bfp["losses"]
            bfp["winrate"] = round(bfp["wins"]/tfp, 4)
            fp_m["por_streak"][fk] = bfp
            fp_m["amostras"] = fp_m.get("amostras",0) + 1
            self._mem["fadiga_padrao"] = fp_m

        # ── 6. Intervalo entre sinais ─────────────────────────────
        iv = self._mem.get("intervalo_sinais", {})
        if iv:
            ult_ts = iv.get("ultimo_sinal_ts","")
            now_str = datetime.now().strftime("%H:%M:%S")
            fiv = "longo_15min+"
            if ult_ts:
                try:
                    from datetime import datetime as dt2, timedelta
                    fmt = "%H:%M:%S"
                    t_ult = dt2.strptime(ult_ts, fmt)
                    t_now = dt2.strptime(now_str, fmt)
                    diff_s = (t_now - t_ult).total_seconds()
                    if diff_s < 0: diff_s += 86400
                    if diff_s <= 60:   fiv = "imediato_0_60s"
                    elif diff_s <= 300: fiv = "curto_1_5min"
                    elif diff_s <= 900: fiv = "medio_5_15min"
                except: pass
            biv = iv.get(fiv, {"wins":0,"losses":0,"winrate":0.0})
            if win: biv["wins"] += 1
            else:   biv["losses"] += 1
            tiv = biv["wins"]+biv["losses"]
            biv["winrate"] = round(biv["wins"]/tiv, 4)
            iv[fiv] = biv
            iv["ultimo_sinal_ts"] = now_str
            iv["amostras"] = iv.get("amostras",0) + 1
            self._mem["intervalo_sinais"] = iv

        # ── 7. Temperatura da sessão ──────────────────────────────
        ts_m = self._mem.get("temperatura_sessao", {})
        if ts_m:
            if win: ts_m["sessao_wins"] = ts_m.get("sessao_wins",0) + 1
            else:   ts_m["sessao_losses"] = ts_m.get("sessao_losses",0) + 1
            sw = ts_m["sessao_wins"]; sl = ts_m["sessao_losses"]
            ts_total = sw + sl
            ts_wr = sw/ts_total if ts_total else 0.0
            ts_m["sessao_winrate"] = round(ts_wr, 4)
            # Faixa de temperatura antes deste sinal
            prev_wr = (sw - (1 if win else 0)) / max(1, ts_total-1) * 100
            if prev_wr < 60:   ft = "fria_lt60"
            elif prev_wr < 75: ft = "morna_60_75"
            elif prev_wr < 90: ft = "quente_75_90"
            else:              ft = "elite_90+"
            bts = ts_m["winrate_por_temperatura"].get(ft, {"wins":0,"losses":0,"winrate":0.0})
            if win: bts["wins"] += 1
            else:   bts["losses"] += 1
            tts = bts["wins"]+bts["losses"]
            bts["winrate"] = round(bts["wins"]/tts, 4)
            ts_m["winrate_por_temperatura"][ft] = bts
            ts_m["amostras"] = ts_m.get("amostras",0) + 1
            self._mem["temperatura_sessao"] = ts_m

        # ── 8. Ciclo do dia ───────────────────────────────────────
        cd = self._mem.get("ciclo_dia", {})
        if cd:
            ck = self._periodo_dia(hora)
            bcd = cd.get(ck, {"wins":0,"losses":0,"winrate":0.0})
            if win: bcd["wins"] += 1
            else:   bcd["losses"] += 1
            tcd = bcd["wins"]+bcd["losses"]
            bcd["winrate"] = round(bcd["wins"]/tcd, 4)
            cd[ck] = bcd
            cd["amostras"] = cd.get("amostras",0) + 1
            self._mem["ciclo_dia"] = cd

        # ── 9. Confiança do ensemble — registra pontos do último veredito
        # (será atualizado em pensar_e_veredictar com o score real)

        # ── 10. Dia da semana ─────────────────────────────────────
        ds = self._mem.get("dia_semana", {})
        if ds:
            dias = ["segunda","terca","quarta","quinta","sexta","sabado","domingo"]
            dia_atual = dias[datetime.now().weekday()]
            bds = ds.get(dia_atual, {"wins":0,"losses":0,"winrate":0.0})
            if win: bds["wins"] += 1
            else:   bds["losses"] += 1
            tds = bds["wins"]+bds["losses"]
            bds["winrate"] = round(bds["wins"]/tds, 4)
            ds[dia_atual] = bds
            ds["amostras"] = ds.get("amostras",0) + 1
            self._mem["dia_semana"] = ds


    # ──────────────────────────────────────────────────────────────
    # MÓDULOS NOVOS DE APRENDIZADO
    # ──────────────────────────────────────────────────────────────

    def _calcular_entropia_shannon(self, history: list, janela: int = 20) -> float:
        """H(x) de Shannon na janela VP — 0=previsível, 1=máximo caos."""
        import math
        vp = [c for c in history if c in ("V","P","B")][-janela:]
        if len(vp) < 5: return 0.5
        total = len(vp)
        freq = {}
        for c in vp: freq[c] = freq.get(c,0)+1
        h = 0.0
        for cnt in freq.values():
            p = cnt/total
            h -= p * math.log2(p)
        return round(h/math.log2(3), 4)  # normaliza para [0,1]

    def _atualizar_entropia(self, history: list, win: bool):
        """Registra entropia atual e correlaciona com win/loss."""
        h_val = self._calcular_entropia_shannon(history)
        ent   = self._mem.get("entropia", {})
        if not ent: return

        hist_h = ent.get("historico_h", [])
        hist_h.append(h_val)
        if len(hist_h) > 200: hist_h = hist_h[-200:]
        ent["historico_h"] = hist_h
        ent["media_h"]     = round(sum(hist_h)/len(hist_h), 4)
        ent["h_maximo"]    = max(ent.get("h_maximo",0), h_val)
        ent["h_minimo"]    = min(ent.get("h_minimo",1), h_val)
        ent["amostras"]    = ent.get("amostras",0) + 1

        # Faixa
        if h_val < 0.70:   faixa = "baixa_0_07"
        elif h_val < 0.90: faixa = "media_07_09"
        elif h_val < 1.00: faixa = "alta_09_099"
        else:              faixa = "maxima_1"

        pf = ent["wins_por_faixa_h"].get(faixa, {"wins":0,"total":0,"winrate":0.0})
        pf["total"] += 1
        if win: pf["wins"] += 1
        pf["winrate"] = round(pf["wins"]/pf["total"], 4)
        ent["wins_por_faixa_h"][faixa] = pf
        self._mem["entropia"] = ent

    def _atualizar_markov(self, history: list):
        """Atualiza matriz de transição V/P/B e sequências de 3."""
        mk = self._mem.get("markov", {})
        if not mk: return

        vp_all = [c for c in history if c in ("V","P","B")]
        if len(vp_all) < 2: return

        # Transições par a par
        trans = mk.get("transicoes", {})
        a, b  = vp_all[-2], vp_all[-1]
        chave = f"{a}→{b}"
        if chave in trans:
            trans[chave]["count"] = trans[chave].get("count",0) + 1
        # Recalcula probabilidades de cada origem
        for origem in ("V","P","B"):
            total_orig = sum(trans[f"{origem}→{d}"]["count"]
                            for d in ("V","P","B") if f"{origem}→{d}" in trans)
            if total_orig > 0:
                for dest in ("V","P","B"):
                    k2 = f"{origem}→{dest}"
                    if k2 in trans:
                        trans[k2]["prob"] = round(trans[k2]["count"]/total_orig, 4)
        mk["transicoes"] = trans

        # Sequências de 3 (ex: "VPV")
        if len(vp_all) >= 3:
            seq3 = "".join(vp_all[-3:])
            seqs = mk.get("sequencias_3", {})
            if seq3 not in seqs:
                seqs[seq3] = {"count": 0}
            seqs[seq3]["count"] += 1
            # Manter só top 50
            if len(seqs) > 50:
                menor = min(seqs.items(), key=lambda x: x[1]["count"])
                del seqs[menor[0]]
            mk["sequencias_3"] = seqs

        mk["amostras"] = mk.get("amostras",0) + 1
        self._mem["markov"] = mk

    def _atualizar_fingerprint(self, win: bool, score: float, hora: str,
                                predicao: str, seca_v: int, seca_p: int, regime: str):
        """Aprende o perfil exato do erro — quando e como os losses acontecem."""
        fl = self._mem.get("fingerprint_loss", {})
        if not fl: return

        seca_pred = seca_v if predicao == "V" else seca_p
        n_win = fl.get("total_losses_analisados", 0)  # reutilizo como contador total

        if not win:
            tot = fl.get("total_losses_analisados", 0) + 1
            fl["total_losses_analisados"] = tot
            # Score médio no loss
            fl["score_medio_loss"] = round(
                (fl.get("score_medio_loss",0) * (tot-1) + score) / tot, 2)
            # Seca média da cor prevista no loss
            fl["seca_pred_media_loss"] = round(
                (fl.get("seca_pred_media_loss",0) * (tot-1) + seca_pred) / tot, 2)
            # Hora e regime
            fl["hora_mais_losses"][hora] = fl.get("hora_mais_losses",{}).get(hora,0) + 1
            fl["regime_mais_losses"][regime] = fl.get("regime_mais_losses",{}).get(regime,0) + 1
        else:
            # Seca média da cor prevista no win (para comparar)
            tot_w = fl.get("total_wins_analisados", 0) + 1
            fl["total_wins_analisados"] = tot_w
            fl["seca_pred_media_win"] = round(
                (fl.get("seca_pred_media_win",0) * (tot_w-1) + seca_pred) / tot_w, 2)

        self._mem["fingerprint_loss"] = fl

    def _atualizar_pressao(self, history: list, win: bool, predicao: str):
        """
        Pressão acumulada — modelo de 'mola'.
        Cada rodada sem V aumenta pressão de V. Quando V aparece, zera.
        No momento do win, registra a pressão.
        """
        pr = self._mem.get("pressao_acumulada", {})
        if not pr: return

        vp_all = [c for c in history if c in ("V","P","B")]
        if not vp_all: return
        ultima = vp_all[-1]

        for cor in ("V","P"):
            bloco = pr.get(cor, {})
            if ultima == cor:
                # Cor saiu — registra pressão atual e zera
                pressao = bloco.get("pressao_atual", 0.0)
                if win and predicao == cor and pressao > 0:
                    hist_p = bloco.get("historico_pressao_no_win",[])
                    hist_p.append(round(pressao,3))
                    if len(hist_p) > 200: hist_p = hist_p[-200:]
                    bloco["historico_pressao_no_win"] = hist_p
                    bloco["media_pressao_win"] = round(sum(hist_p)/len(hist_p), 3)
                    # Pressão crítica = percentil 30 (maioria dos wins acima disso)
                    sorted_p = sorted(hist_p)
                    idx_30 = max(0, int(len(sorted_p)*0.30))
                    bloco["pressao_critica"] = sorted_p[idx_30]
                bloco["pressao_atual"] = 0.0
            else:
                # Cor não saiu — aumenta pressão (logaritmico para evitar explosão)
                import math
                bloco["pressao_atual"] = round(
                    bloco.get("pressao_atual",0.0) + 1.0 / (1 + bloco.get("pressao_atual",0.0)), 3)
            pr[cor] = bloco

        self._mem["pressao_acumulada"] = pr



    def _atualizar_score_hora(self, win: bool, score: float, hora: str):
        """Score + Hora combinados — 95 às 04h ≠ 95 às 20h."""
        fsc   = self._faixa_score(score)
        chave = f"{hora}h_{fsc}"
        sh    = self._mem.get("score_hora_combo", {})
        if chave not in sh:
            sh[chave] = {"wins": 0, "losses": 0, "winrate": 0.0}
        if win: sh[chave]["wins"]   += 1
        else:   sh[chave]["losses"] += 1
        t = sh[chave]["wins"] + sh[chave]["losses"]
        sh[chave]["winrate"] = round(sh[chave]["wins"] / t, 4)
        self._mem["score_hora_combo"] = sh

    def _atualizar_seca_combo(self, win: bool, seca_v: int, seca_p: int):
        """Seca V e P simultânea — (5,0) é diferente de (5,5)."""
        # Buckeia para não explodir o dicionário
        bv = min(seca_v, 10)
        bp = min(seca_p, 10)
        chave = f"V{bv}P{bp}"
        sc = self._mem.get("seca_combo", {"wins": {}, "losses": {}, "risco_combos": []})
        lista = "wins" if win else "losses"
        sc[lista][chave] = sc[lista].get(chave, 0) + 1

        # Atualiza combos de risco: combos com > 3 losses e winrate < 50%
        risco = []
        todos = set(sc["wins"].keys()) | set(sc["losses"].keys())
        for k in todos:
            w = sc["wins"].get(k, 0)
            l = sc["losses"].get(k, 0)
            t = w + l
            if t >= 5 and l / t >= 0.5:
                risco.append({"combo": k, "wins": w, "losses": l,
                               "winrate": round(w/t, 4)})
        risco.sort(key=lambda x: x["winrate"])
        sc["risco_combos"] = risco[:10]
        self._mem["seca_combo"] = sc

    def _atualizar_velocidade(self, win: bool, hora_str: str):
        """Velocidade do mercado — sinal rápido vs sinal isolado."""
        from datetime import datetime
        vm = self._mem.get("velocidade_mercado", {})
        ts_list = vm.get("timestamps_sinais", [])

        agora = datetime.now().timestamp()
        ts_list.append(agora)
        if len(ts_list) > 50:
            ts_list = ts_list[-50:]
        vm["timestamps_sinais"] = ts_list

        # Intervalo desde o sinal anterior
        if len(ts_list) >= 2:
            intervalo_seg = agora - ts_list[-2]
            if intervalo_seg >= 300:   faixa = "lento_5+min"
            elif intervalo_seg >= 60:  faixa = "normal_1_5min"
            else:                      faixa = "rapido_lt1min"

            pv = vm.get("por_velocidade", {})
            if faixa not in pv:
                pv[faixa] = {"wins": 0, "total": 0, "winrate": 0.0}
            pv[faixa]["total"] += 1
            if win: pv[faixa]["wins"] += 1
            pv[faixa]["winrate"] = round(pv[faixa]["wins"] / pv[faixa]["total"], 4)
            vm["por_velocidade"] = pv
        self._mem["velocidade_mercado"] = vm

    def _atualizar_padrao_pre_loss(self, win: bool, history: list):
        """Sequência de 5 cores antes de cada loss — padrão pré-erro."""
        if win:
            return
        vp = [c for c in history if c in ("V", "P", "B")][-6:-1]  # 5 antes
        if len(vp) < 5:
            return
        seq = "".join(vp)
        ppl = self._mem.get("padrao_pre_loss", {"sequencias": {}, "top_perdedoras": []})
        ppl["sequencias"][seq] = ppl["sequencias"].get(seq, 0) + 1

        # Top 10 sequências que mais precedem losses
        top = sorted(ppl["sequencias"].items(), key=lambda x: x[1], reverse=True)[:10]
        ppl["top_perdedoras"] = [{"seq": k, "count": v} for k, v in top]
        self._mem["padrao_pre_loss"] = ppl

    def _atualizar_fadiga(self, win: bool, nome_padrao: str):
        """Fadiga do padrão específico — acerta menos após muitos wins seguidos?"""
        if not nome_padrao:
            return
        fd = self._mem.get("fadiga_padrao", {})
        if nome_padrao not in fd:
            fd[nome_padrao] = {
                "wins_consecutivos": 0,
                "historico": [],   # lista de (wins_consec_antes, resultado)
                "fadiga_detectada": False
            }
        bloco = fd[nome_padrao]
        # Registra resultado com o streak atual
        bloco["historico"].append({
            "streak_antes": bloco["wins_consecutivos"],
            "win": win
        })
        if len(bloco["historico"]) > 50:
            bloco["historico"] = bloco["historico"][-50:]

        if win:
            bloco["wins_consecutivos"] += 1
        else:
            # Detecta fadiga: mais de 5 wins seguidos E esse foi loss
            if bloco["wins_consecutivos"] >= 5:
                bloco["fadiga_detectada"] = True
            bloco["wins_consecutivos"] = 0

        fd[nome_padrao] = bloco
        self._mem["fadiga_padrao"] = fd

    def _detectar_mudanca_comportamento(self, win: bool):
        """
        Detecta mudança brusca: compara winrate das últimas 10
        com as 10 anteriores. Queda > 30pp = comportamento mudou.
        """
        mc = self._mem.get("mudanca_comportamento", {
            "historico_wr_janela": [], "alerta_ativo": False,
            "ultimo_alerta": "", "nivel": "normal"
        })
        hist = mc.get("historico_wr_janela", [])
        hist.append(1 if win else 0)
        if len(hist) > 40:
            hist = hist[-40:]
        mc["historico_wr_janela"] = hist

        if len(hist) >= 20:
            wr_recente  = sum(hist[-10:]) / 10
            wr_anterior = sum(hist[-20:-10]) / 10
            queda       = wr_anterior - wr_recente

            if queda >= 0.40:
                mc["alerta_ativo"]  = True
                mc["nivel"]         = "critico"
                from datetime import datetime
                mc["ultimo_alerta"] = datetime.now().strftime("%H:%M")
            elif queda >= 0.25:
                mc["alerta_ativo"]  = True
                mc["nivel"]         = "atencao"
                from datetime import datetime
                mc["ultimo_alerta"] = datetime.now().strftime("%H:%M")
            else:
                mc["alerta_ativo"] = False
                mc["nivel"]        = "normal"

        self._mem["mudanca_comportamento"] = mc


    def _gerar_conclusoes(self, win, score, hora, predicao, seca_v, seca_p,
                           regime, loss_antes, win_antes):
        """Detecta padrões incomuns e registra como conclusões aprendidas."""
        from datetime import datetime
        conclusoes = self._mem["conclusoes_aprendidas"]
        now = datetime.now().strftime("%H:%M")

        # Máximo de 30 conclusões
        if len(conclusoes) >= 30:
            conclusoes.pop(0)

        if not win:
            # Loss com score alto — evento notável
            if score >= 90:
                conclusoes.append({
                    "ts": now, "tipo": "loss_score_alto",
                    "msg": f"Loss com score {score:.0f} — alta confiança falhou. Hora: {hora}h | Regime: {regime}"
                })
            # Cluster de losses
            ultimos = self._mem["ultimos_50"][-10:]
            losses_recentes = sum(1 for r in ultimos if not r["win"])
            if losses_recentes >= 4:
                conclusoes.append({
                    "ts": now, "tipo": "cluster_loss",
                    "msg": f"{losses_recentes}/10 últimas entradas foram losses — mercado em turbulência"
                })
        else:
            # Win após longa seca de V/P
            pn = self._mem["padroes_notaveis"]
            if seca_v >= pn.get("seca_ideal_V", 0) * 1.5 and pn.get("seca_ideal_V", 0) > 0:
                conclusoes.append({
                    "ts": now, "tipo": "win_seca_extrema",
                    "msg": f"Win com seca V={seca_v} (150%+ da média ideal {pn['seca_ideal_V']:.1f}) — seca extrema confirmada como gatilho"
                })
            # Win após vários losses
            if loss_antes >= 2:
                pl = self._mem["pos_loss"].get(f"apos_{min(loss_antes,3)}_loss", {})
                if pl.get("total", 0) >= 5:
                    conclusoes.append({
                        "ts": now, "tipo": "recuperacao",
                        "msg": f"Win após {loss_antes} losses consecutivos — taxa de recuperação histórica: {pl['winrate']*100:.0f}%"
                    })

        self._mem["conclusoes_aprendidas"] = conclusoes

    # ──────────────────────────────────────────────────────────────
    # VEREDITO — chamado antes de enviar o sinal
    # ──────────────────────────────────────────────────────────────

    def pensar_e_veredictar(
        self,
        score: float,
        hora: str,
        predicao: str,
        history: list,
        regime: str,
        loss_streak_atual: int,
        win_streak_atual:  int,
        nome_padrao: str,
    ) -> str:
        """
        Motor principal de veredito — analisa 10 dimensões, gera texto
        100% dinâmico com números reais. Nunca usa texto pré-definido.
        """
        seca_v = self._calcular_seca(history, "V")
        seca_p = self._calcular_seca(history, "P")
        seca_b = self._calcular_seca(history, "B")
        h      = hora[:2]
        fsc    = self._faixa_score(score)
        pn     = self._mem["padroes_notaveis"]
        total  = self._mem["meta"]["total_entradas"]

        pontos  = 0
        motivos = []

        # ── 1. SCORE com texto dinâmico ───────────────────────────
        ps   = self._mem["por_score"].get(fsc, {"wins":0,"losses":0,"winrate":0.0})
        t_sc = ps["wins"] + ps["losses"]
        if t_sc >= self.MIN_AMOSTRAS:
            wr_sc = ps["winrate"] * 100
            fsc_label = {"95-100":"95-100","90-94":"90-94","85-89":"85-89",
                         "80-84":"80-84","lt80":"abaixo de 80"}.get(fsc, fsc)
            if score >= 95:
                motivos.append((+3,"⚡",
                    f"Score {score:.0f} — nessa faixa o padrão acertou "
                    f"{ps['wins']} de {t_sc} vezes ({wr_sc:.0f}%)"))
                pontos += 3
            elif score >= 90:
                motivos.append((+2,"✅",
                    f"Score {score:.0f} — faixa 90-94 tem {wr_sc:.0f}% de acerto "
                    f"({ps['wins']}W/{ps['losses']}L em {t_sc} sinais)"))
                pontos += 2
            elif score >= 85:
                motivos.append((+1,"🟡",
                    f"Score {score:.0f} — faixa 85-89 acerta {wr_sc:.0f}% "
                    f"({ps['wins']}W/{ps['losses']}L)"))
                pontos += 1
            elif score >= pn.get("score_critico",85):
                motivos.append((0,"🟡",
                    f"Score {score:.0f} — faixa 80-84 acerta {wr_sc:.0f}% "
                    f"({ps['wins']}W/{ps['losses']}L)"))
            else:
                motivos.append((-2,"⚠️",
                    f"Score {score:.0f} está abaixo do limiar crítico — "
                    f"faixa {fsc_label} acerta apenas {wr_sc:.0f}% "
                    f"({ps['wins']}W/{ps['losses']}L)"))
                pontos -= 2

        # ── 2. HORA com texto dinâmico ────────────────────────────
        ph   = self._mem["por_hora"].get(h, {"wins":0,"losses":0,"winrate":0.0})
        t_h  = ph["wins"] + ph["losses"]
        if t_h >= self.MIN_AMOSTRAS:
            wr_h = ph["winrate"] * 100
            if wr_h >= 87:
                motivos.append((+2,"🕐",
                    f"Hora {h}h — historicamente {ph['wins']}W/{ph['losses']}L "
                    f"= {wr_h:.0f}% de acerto ({t_h} sinais registrados)"))
                pontos += 2
            elif wr_h >= 82:
                motivos.append((+1,"🕐",
                    f"Hora {h}h com {wr_h:.0f}% de acerto "
                    f"({ph['wins']}W/{ph['losses']}L em {t_h} sinais)"))
                pontos += 1
            elif wr_h < 65:
                motivos.append((-2,"🕐",
                    f"Hora {h}h é perigosa — apenas {wr_h:.0f}% de acerto "
                    f"({ph['wins']}W/{ph['losses']}L em {t_h} sinais)"))
                pontos -= 2
            elif wr_h < 75:
                motivos.append((-1,"🕐",
                    f"Hora {h}h abaixo da média — {wr_h:.0f}% "
                    f"({ph['wins']}W/{ph['losses']}L)"))
                pontos -= 1

        # ── 3. ENTROPIA — mede o caos do mercado ─────────────────
        ent = self._mem.get("entropia", {})
        if ent.get("amostras",0) >= self.MIN_AMOSTRAS:
            h_val   = self._calcular_entropia_shannon(history)
            media_h = ent.get("media_h", 0.5)
            faixas_h = ent.get("wins_por_faixa_h", {})

            if h_val < 0.70:
                fh = faixas_h.get("baixa_0_07",{"wins":0,"total":0,"winrate":0.0})
                if fh["total"] >= 5:
                    motivos.append((+2,"📉",
                        f"Entropia baixa ({h_val:.2f}) — mercado previsível. "
                        f"Nessa faixa o acerto histórico é {fh['winrate']*100:.0f}%"))
                    pontos += 2
            elif h_val >= 1.0:
                fh = faixas_h.get("maxima_1",{"wins":0,"total":0,"winrate":0.0})
                if fh["total"] >= 5:
                    motivos.append((-2,"📈",
                        f"Entropia máxima ({h_val:.2f}) — mercado no caos total. "
                        f"Nessa faixa acerta {fh['winrate']*100:.0f}%"))
                    pontos -= 2
            elif h_val >= 0.90:
                fh = faixas_h.get("alta_09_099",{"wins":0,"total":0,"winrate":0.0})
                if fh["total"] >= 5:
                    motivos.append((-1,"📊",
                        f"Entropia alta ({h_val:.2f}) — mercado instável. "
                        f"Acerto histórico: {fh['winrate']*100:.0f}%"))
                    pontos -= 1
            else:
                motivos.append((0,"📊",
                    f"Entropia moderada ({h_val:.2f}) — mercado em transição"))

        # ── 4. MARKOV — probabilidade real de transição ───────────
        mk = self._mem.get("markov", {})
        if mk.get("amostras",0) >= 20:
            trans = mk.get("transicoes", {})
            vp_all = [c for c in history if c in ("V","P","B")]
            if vp_all:
                ultima_cor = vp_all[-1]
                chave_para = f"{ultima_cor}→{predicao}"
                chave_cont = f"{ultima_cor}→{ultima_cor}"
                prob_pred  = trans.get(chave_para,{}).get("prob",0)
                prob_cont  = trans.get(chave_cont,{}).get("prob",0)
                count_pred = trans.get(chave_para,{}).get("count",0)
                if count_pred >= 10:
                    if prob_pred >= 0.65:
                        motivos.append((+2,"🔀",
                            f"Markov: após {ultima_cor}, {predicao} saiu "
                            f"{prob_pred*100:.0f}% das vezes "
                            f"({count_pred} ocorrências aprendidas)"))
                        pontos += 2
                    elif prob_pred >= 0.50:
                        motivos.append((+1,"🔀",
                            f"Markov: {ultima_cor}→{predicao} = {prob_pred*100:.0f}% "
                            f"({count_pred} casos)"))
                        pontos += 1
                    elif prob_pred < 0.35:
                        motivos.append((-2,"🔀",
                            f"Markov: após {ultima_cor}, {predicao} é improvável — "
                            f"só {prob_pred*100:.0f}% ({count_pred} casos). "
                            f"A tendência é {ultima_cor} ({prob_cont*100:.0f}%)"))
                        pontos -= 2

        # ── 5. PRESSÃO ACUMULADA ──────────────────────────────────
        pr = self._mem.get("pressao_acumulada", {})
        cor_pred_key = "V" if predicao == "V" else "P"
        bloco_pr = pr.get(cor_pred_key, {})
        pressao_atual  = bloco_pr.get("pressao_atual", 0.0)
        pressao_critica = bloco_pr.get("pressao_critica", 0.0)
        media_pr_win   = bloco_pr.get("media_pressao_win", 0.0)
        hist_pr        = bloco_pr.get("historico_pressao_no_win", [])

        if len(hist_pr) >= 10 and media_pr_win > 0:
            ratio = pressao_atual / media_pr_win if media_pr_win > 0 else 0
            if ratio >= 1.5:
                motivos.append((+2,"🌡️",
                    f"Pressão {predicao} acima da média de wins ({pressao_atual:.2f} vs "
                    f"média {media_pr_win:.2f}) — mola tensa, pronta para soltar"))
                pontos += 2
            elif ratio >= 1.0:
                motivos.append((+1,"🌡️",
                    f"Pressão {predicao} na zona de wins ({pressao_atual:.2f}, "
                    f"média histórica {media_pr_win:.2f})"))
                pontos += 1
            elif ratio < 0.4:
                motivos.append((-1,"🌡️",
                    f"Pressão {predicao} baixa ({pressao_atual:.2f}) — "
                    f"cor apareceu recentemente, ainda sem acúmulo"))
                pontos -= 1

        # ── 6. FINGERPRINT — este sinal tem perfil de loss? ───────
        fl = self._mem.get("fingerprint_loss", {})
        if fl.get("total_losses_analisados",0) >= 10:
            score_med_loss = fl.get("score_medio_loss", 0)
            hora_losses    = fl.get("hora_mais_losses", {})
            regime_losses  = fl.get("regime_mais_losses", {})
            seca_pred_loss = fl.get("seca_pred_media_loss", 0)
            seca_pred_win  = fl.get("seca_pred_media_win", 0)
            tot_loss       = fl.get("total_losses_analisados",1)

            # Hora perigosa?
            perigo_hora = hora_losses.get(h, 0)
            if perigo_hora >= 3:
                pct_hora_loss = perigo_hora / tot_loss * 100
                motivos.append((-1,"🔍",
                    f"Perfil de erro: {perigo_hora} dos {tot_loss} losses "
                    f"aconteceram às {h}h ({pct_hora_loss:.0f}% dos erros)"))
                pontos -= 1

            # Score parecido com o médio dos losses?
            if abs(score - score_med_loss) <= 5 and score < 85:
                motivos.append((-1,"🔍",
                    f"Perfil de erro: score {score:.0f} próximo da média dos losses "
                    f"({score_med_loss:.0f}) — atenção redobrada"))
                pontos -= 1

            # Seca da cor prevista parecida com a dos wins
            seca_pred_atual = seca_v if predicao=="V" else seca_p
            if seca_pred_win > 0 and seca_pred_loss > 0:
                dist_win  = abs(seca_pred_atual - seca_pred_win)
                dist_loss = abs(seca_pred_atual - seca_pred_loss)
                if dist_win < dist_loss:
                    motivos.append((+1,"🔍",
                        f"Seca {predicao}={seca_pred_atual} mais próxima do padrão "
                        f"de win ({seca_pred_win:.1f}) do que de loss ({seca_pred_loss:.1f})"))
                    pontos += 1

        # ── 7. SECA DA COR PREVISTA ───────────────────────────────
        seca_pred_val = seca_v if predicao=="V" else seca_p
        cor_nome_lbl  = "vermelho" if predicao=="V" else "preto"
        bloco_seca    = self._mem["seca_no_sinal"].get(predicao, {})
        n_wins_seca   = len(bloco_seca.get("wins",[]))
        if n_wins_seca >= self.MIN_AMOSTRAS:
            media_win_seca = bloco_seca.get("media_win", 0)
            dist_seca      = bloco_seca.get("distribuicao_wins", {})
            wins_abaixo    = sum(v for k,v in dist_seca.items() if int(k)<=seca_pred_val)
            pct            = wins_abaixo/n_wins_seca*100 if n_wins_seca else 50
            if seca_pred_val >= media_win_seca*1.5 and seca_pred_val >= 3:
                motivos.append((+1,"🔴",
                    f"Seca {predicao}={seca_pred_val} — 50%+ acima da média de wins "
                    f"({media_win_seca:.1f}). {pct:.0f}% dos wins ocorreram com seca ≤{seca_pred_val}"))
                pontos += 1
            elif pct <= 25 and seca_pred_val < media_win_seca*0.5:
                motivos.append((-1,"🟢",
                    f"Seca {predicao}={seca_pred_val} abaixo do normal — "
                    f"apenas {pct:.0f}% dos wins com seca tão baixa"))
                pontos -= 1
            else:
                motivos.append((0,"📡",
                    f"Seca {predicao}={seca_pred_val} (média dos wins: {media_win_seca:.1f}). "
                    f"{pct:.0f}% dos {n_wins_seca} wins históricos ocorreram com seca ≤{seca_pred_val}"))

        # ── 8. PÓS-LOSS ───────────────────────────────────────────
        if loss_streak_atual >= 1:
            chave_pl = f"apos_{min(loss_streak_atual,3)}_loss"
            pl       = self._mem["pos_loss"].get(chave_pl, {})
            t_pl     = pl.get("total",0)
            if t_pl >= self.MIN_AMOSTRAS:
                wr_pl = pl["winrate"]*100
                n_win_pl = pl["wins"]
                motivos.append(
                    (+2 if wr_pl>=85 else +1 if wr_pl>=80 else 0,
                     "🔄",
                     f"Vem de {loss_streak_atual} loss(es) — histórico de recuperação: "
                     f"{n_win_pl}/{t_pl} = {wr_pl:.0f}% de win no próximo sinal"))
                pontos += 2 if wr_pl>=85 else 1 if wr_pl>=80 else 0

        # ── 9. MOMENTUM ───────────────────────────────────────────
        moment = self._mem.get("momentum_recente",[])
        if len(moment) >= 10:
            ult10 = moment[-10:]
            ult5  = moment[-5:]
            w10   = sum(ult10); w5 = sum(ult5)
            wr10  = w10/10*100; wr5 = w5/5*100
            if wr10 >= 90:
                motivos.append((+1,"🔥",
                    f"Momentum excelente: {w10}/10 wins recentes. "
                    f"Últimas 5: {w5}/5 wins"))
                pontos += 1
            elif wr10 <= 50:
                motivos.append((-2,"💀",
                    f"Momentum fraco: apenas {w10}/10 wins recentes ({wr10:.0f}%) — "
                    f"possível cluster de losses em formação"))
                pontos -= 2
            elif wr10 <= 65:
                motivos.append((-1,"🌀",
                    f"Momentum irregular: {w10}/10 wins recentes ({wr10:.0f}%)"))
                pontos -= 1

        # ── 10. REGIME ────────────────────────────────────────────
        pr_reg = self._mem["por_regime"].get(regime,{"wins":0,"losses":0,"winrate":0.0})
        t_reg  = pr_reg["wins"]+pr_reg["losses"]
        if t_reg >= self.MIN_AMOSTRAS:
            wr_reg = pr_reg["winrate"]*100
            if wr_reg >= 85:
                motivos.append((+1,"🌊",
                    f"Regime {regime}: {pr_reg['wins']}W/{pr_reg['losses']}L "
                    f"= {wr_reg:.0f}% histórico ({t_reg} entradas)"))
                pontos += 1
            elif wr_reg < 70:
                motivos.append((-1,"🌀",
                    f"Regime {regime}: apenas {wr_reg:.0f}% histórico "
                    f"({pr_reg['wins']}W/{pr_reg['losses']}L em {t_reg} entradas)"))
                pontos -= 1

        # ── MÓDULOS EXTRAS (1-10) ─────────────────────────────────

        # 1. Score + Hora
        sh = self._mem.get("score_hora",{})
        if sh.get("amostras",0) >= 10:
            sc_h = score
            if sc_h >= 95: fsc_h = "95+"
            elif sc_h >= 90: fsc_h = "90-94"
            elif sc_h >= 85: fsc_h = "85-89"
            else: fsc_h = "lt85"
            chave_sh = f"{h}h_{fsc_h}"
            bsh = sh.get("dados",{}).get(chave_sh)
            if bsh and bsh["wins"]+bsh["losses"] >= 5:
                wr_sh = bsh["winrate"]*100
                t_sh  = bsh["wins"]+bsh["losses"]
                if wr_sh >= 85:
                    motivos.append((+2,"🎯",
                        f"Score {score:.0f} às {h}h: combinação acertou "
                        f"{bsh['wins']}/{t_sh} = {wr_sh:.0f}% ({t_sh} casos)"))
                    pontos += 2
                elif wr_sh < 60:
                    motivos.append((-2,"🎯",
                        f"Score {score:.0f} às {h}h: combinação tem apenas "
                        f"{wr_sh:.0f}% de acerto ({bsh['wins']}/{t_sh} casos)"))
                    pontos -= 2

        # 2. Seca dupla V+P
        sd = self._mem.get("seca_dupla",{})
        if sd.get("amostras",0) >= 10:
            sv_c = min(seca_v,9); sp_c = min(seca_p,9)
            fv = "0" if sv_c==0 else "1-2" if sv_c<=2 else "3-5" if sv_c<=5 else "6+"
            fp = "0" if sp_c==0 else "1-2" if sp_c<=2 else "3-5" if sp_c<=5 else "6+"
            chave_sd = f"V{fv}_P{fp}"
            bsd = sd.get("dados",{}).get(chave_sd)
            if bsd and bsd["wins"]+bsd["losses"] >= 5:
                wr_sd = bsd["winrate"]*100
                t_sd  = bsd["wins"]+bsd["losses"]
                if wr_sd >= 85:
                    motivos.append((+1,"🧩",
                        f"Combinação seca V={seca_v}+P={seca_p} acertou "
                        f"{bsd['wins']}/{t_sd} = {wr_sd:.0f}%"))
                    pontos += 1
                elif wr_sd < 50:
                    motivos.append((-1,"🧩",
                        f"Combinação seca V={seca_v}+P={seca_p} tem só "
                        f"{wr_sd:.0f}% ({bsd['wins']}/{t_sd} casos)"))
                    pontos -= 1
            # Comparar com perfil de loss
            perfil_loss = sd.get("perfil_loss",[])
            if len(perfil_loss) >= 5:
                media_sv_loss = sum(x[0] for x in perfil_loss)/len(perfil_loss)
                media_sp_loss = sum(x[1] for x in perfil_loss)/len(perfil_loss)
                if abs(seca_v-media_sv_loss)<=1 and abs(seca_p-media_sp_loss)<=1:
                    motivos.append((-1,"🧩",
                        f"Seca V={seca_v}/P={seca_p} próxima do perfil médio "
                        f"dos losses (V={media_sv_loss:.1f}/P={media_sp_loss:.1f})"))
                    pontos -= 1

        # 3. Velocidade do mercado
        vm = self._mem.get("velocidade_mercado",{})
        if vm.get("amostras",0) >= 10:
            vel = len(vm.get("timestamps_sinais",[]))
            if vel <= 3:   fvel,lbl = "lento_0_3","lento"
            elif vel <= 8: fvel,lbl = "normal_4_8","normal"
            elif vel <= 15:fvel,lbl = "rapido_9_15","rápido"
            else:          fvel,lbl = "acelerado_15+","acelerado"
            bvm = vm.get(fvel,{"wins":0,"losses":0,"winrate":0.0})
            t_vm = bvm["wins"]+bvm["losses"]
            if t_vm >= 5:
                wr_vm = bvm["winrate"]*100
                if wr_vm >= 85:
                    motivos.append((+1,"⚡",
                        f"Mercado {lbl} ({vel} sinais/h): acerta {wr_vm:.0f}% "
                        f"({bvm['wins']}/{t_vm})"))
                    pontos += 1
                elif wr_vm < 60:
                    motivos.append((-1,"⚡",
                        f"Mercado {lbl} tem apenas {wr_vm:.0f}% "
                        f"({bvm['wins']}/{t_vm})"))
                    pontos -= 1

        # 4. Padrão pré-loss
        ppl = self._mem.get("padrao_pre_loss",{})
        if ppl.get("amostras_loss",0) >= 5:
            vp_pre = [c for c in history if c in ("V","P")][-5:]
            if len(vp_pre) == 5:
                seq5 = "".join(vp_pre)
                seq_dados = ppl.get("sequencias",{}).get(seq5)
                top_per   = ppl.get("top_perigosas",[])
                seqs_per  = [x["seq"] for x in top_per]
                if seq5 in seqs_per and seq_dados:
                    tl = seq_dados["taxa_loss"]*100
                    motivos.append((-2,"☠️",
                        f"Sequência {seq5} antes do sinal está no top de "
                        f"perigosas — {tl:.0f}% de taxa de loss "
                        f"({seq_dados['count_loss']} losses)"))
                    pontos -= 2
                elif seq_dados and seq_dados["taxa_loss"] >= 0.6:
                    motivos.append((-1,"☠️",
                        f"Padrão pré-sinal {seq5} tem {seq_dados['taxa_loss']*100:.0f}% "
                        f"de taxa de loss ({seq_dados['count_loss']} registros)"))
                    pontos -= 1

        # 5. Fadiga do padrão
        fp_m = self._mem.get("fadiga_padrao",{})
        if fp_m.get("amostras",0) >= 15:
            fk = self._faixa_streak(win_streak_atual)
            bfp = fp_m["por_streak"].get(fk,{"wins":0,"losses":0,"winrate":0.0})
            t_fp = bfp["wins"]+bfp["losses"]
            if t_fp >= 5:
                wr_fp = bfp["winrate"]*100
                if wr_fp >= 85:
                    motivos.append((+1,"💪",
                        f"Padrão em streak {fk}: {wr_fp:.0f}% de acerto "
                        f"({bfp['wins']}/{t_fp} casos)"))
                    pontos += 1
                elif wr_fp < 65:
                    motivos.append((-1,"😴",
                        f"Padrão em streak {fk} fadiga: cai para {wr_fp:.0f}% "
                        f"({bfp['wins']}/{t_fp} casos)"))
                    pontos -= 1

        # 6. Intervalo entre sinais
        iv = self._mem.get("intervalo_sinais",{})
        if iv.get("amostras",0) >= 10:
            ult_ts = iv.get("ultimo_sinal_ts","")
            fiv = "longo_15min+"
            lbl_iv = "isolado"
            if ult_ts:
                try:
                    from datetime import datetime as dt2
                    fmt = "%H:%M:%S"
                    t_ult = dt2.strptime(ult_ts, fmt)
                    t_now = dt2.strptime(hora, fmt)
                    diff_s = (t_now-t_ult).total_seconds()
                    if diff_s < 0: diff_s += 86400
                    if diff_s <= 60:   fiv,lbl_iv = "imediato_0_60s","imediato (<1min)"
                    elif diff_s <= 300: fiv,lbl_iv = "curto_1_5min","curto (1-5min)"
                    elif diff_s <= 900: fiv,lbl_iv = "medio_5_15min","médio (5-15min)"
                except: pass
            biv = iv.get(fiv,{"wins":0,"losses":0,"winrate":0.0})
            t_iv = biv["wins"]+biv["losses"]
            if t_iv >= 5:
                wr_iv = biv["winrate"]*100
                if wr_iv < 65:
                    motivos.append((-1,"⏱️",
                        f"Intervalo {lbl_iv}: acerta só {wr_iv:.0f}% "
                        f"({biv['wins']}/{t_iv} casos)"))
                    pontos -= 1
                elif wr_iv >= 85:
                    motivos.append((+1,"⏱️",
                        f"Intervalo {lbl_iv}: {wr_iv:.0f}% de acerto "
                        f"({biv['wins']}/{t_iv} casos)"))
                    pontos += 1

        # 7. Temperatura da sessão
        ts_m = self._mem.get("temperatura_sessao",{})
        if ts_m.get("amostras",0) >= 5:
            sw = ts_m.get("sessao_wins",0)
            sl = ts_m.get("sessao_losses",0)
            ts_tot = sw+sl
            ts_wr  = sw/ts_tot*100 if ts_tot else 0
            if ts_wr >= 85:
                motivos.append((+1,"🌡️",
                    f"Sessão aquecida: {sw}W/{sl}L = {ts_wr:.0f}% nesta sessão"))
                pontos += 1
            elif ts_wr < 60:
                motivos.append((-1,"🌡️",
                    f"Sessão fria: apenas {sw}W/{sl}L = {ts_wr:.0f}% — cautela"))
                pontos -= 1

        # 8. Ciclo do dia
        cd = self._mem.get("ciclo_dia",{})
        if cd.get("amostras",0) >= 20:
            ck = self._periodo_dia(hora)
            bcd = cd.get(ck,{"wins":0,"losses":0,"winrate":0.0})
            t_cd = bcd["wins"]+bcd["losses"]
            lbl_cd = {"manha_06_12":"manhã","tarde_12_18":"tarde",
                      "noite_18_00":"noite","madrugada_00_06":"madrugada"}.get(ck,ck)
            if t_cd >= 10:
                wr_cd = bcd["winrate"]*100
                if wr_cd >= 83:
                    motivos.append((+1,"🌅",
                        f"Período da {lbl_cd}: {bcd['wins']}W/{bcd['losses']}L "
                        f"= {wr_cd:.0f}% histórico"))
                    pontos += 1
                elif wr_cd < 75:
                    motivos.append((-1,"🌅",
                        f"Período da {lbl_cd} mais fraco: "
                        f"{bcd['wins']}W/{bcd['losses']}L = {wr_cd:.0f}%"))
                    pontos -= 1

        # 9. Confiança do ensemble — conta módulos positivos
        modulos_positivos = sum(1 for p,_,_ in motivos if p > 0)
        modulos_negativos = sum(1 for p,_,_ in motivos if p < 0)
        total_modulos = modulos_positivos + modulos_negativos
        ce = self._mem.get("confianca_ensemble",{})
        if total_modulos >= 3:
            pct_concordancia = modulos_positivos/total_modulos*100 if total_modulos else 50
            if pct_concordancia >= 80:
                motivos.append((+1,"🎖️",
                    f"Ensemble: {modulos_positivos}/{total_modulos} módulos favoráveis "
                    f"({pct_concordancia:.0f}% concordam)"))
                pontos += 1
            elif pct_concordancia <= 35:
                motivos.append((-1,"🎖️",
                    f"Ensemble dividido: apenas {modulos_positivos}/{total_modulos} "
                    f"módulos favoráveis ({pct_concordancia:.0f}%)"))
                pontos -= 1

        # 10. Dia da semana
        ds = self._mem.get("dia_semana",{})
        if ds.get("amostras",0) >= 30:
            dias = ["segunda","terca","quarta","quinta","sexta","sabado","domingo"]
            from datetime import datetime as dt3
            dia_atual = dias[dt3.now().weekday()]
            bds = ds.get(dia_atual,{"wins":0,"losses":0,"winrate":0.0})
            t_ds = bds["wins"]+bds["losses"]
            if t_ds >= 10:
                wr_ds = bds["winrate"]*100
                lbl_ds = dia_atual.capitalize()
                if wr_ds >= 85:
                    motivos.append((+1,"📅",
                        f"{lbl_ds}: {bds['wins']}W/{bds['losses']}L "
                        f"= {wr_ds:.0f}% histórico"))
                    pontos += 1
                elif wr_ds < 72:
                    motivos.append((-1,"📅",
                        f"{lbl_ds} é mais fraco: {bds['wins']}W/{bds['losses']}L "
                        f"= {wr_ds:.0f}%"))
                    pontos -= 1

        # ── CALIBRAÇÃO — ajuste pelo histórico do veredito ────────
        # (aplicado DEPOIS de calcular pontos para não criar loop)
        calib = self._mem.get("calibracao",{})
        calib_ajuste = 0

        # ── VEREDITO FINAL ────────────────────────────────────────
        if pontos >= 7:   verd,emoji_v = "EXCELENTE",      "🟢"
        elif pontos >= 5: verd,emoji_v = "MUITO FAVORÁVEL","🟢"
        elif pontos >= 3: verd,emoji_v = "FAVORÁVEL",      "🟡"
        elif pontos >= 1: verd,emoji_v = "NEUTRO-POSITIVO","🟡"
        elif pontos == 0: verd,emoji_v = "NEUTRO",         "⬜"
        elif pontos >= -2:verd,emoji_v = "CAUTELA",        "🟠"
        else:             verd,emoji_v = "DESFAVORÁVEL",   "🔴"

        # Verificar se esse veredito costuma acertar (calibração)
        verd_key = verd.replace(" FAVORÁVEL","_FAV").replace("Ó","O")
        verd_key_clean = verd.upper().replace(" ","_")
        calib_bloco = calib.get("por_veredito",{}).get(verd,{})
        calib_txt = ""
        if calib_bloco.get("total",0) >= 10:
            calib_wr = calib_bloco["winrate"]*100
            calib_total = calib_bloco["total"]
            calib_txt = (
                f"\n📐 <i>Calibração: quando disse '{verd}' antes, acertou "
                f"{calib_bloco['wins']}/{calib_total} = {calib_wr:.0f}%</i>"
            )

        # ── CONCLUSÃO DINÂMICA ────────────────────────────────────
        # Gerada com dados reais, nunca texto fixo
        partes_conclusao = []

        ph_melhor = pn.get("melhor_hora",{})
        ph_pior   = pn.get("pior_hora",{})
        if ph_melhor.get("hora"):
            partes_conclusao.append(
                f"Melhor hora histórica: {ph_melhor['hora']}h ({ph_melhor['winrate']}%)")
        if ph_pior.get("hora") and ph_pior.get("winrate",100) < 70:
            partes_conclusao.append(
                f"evitar {ph_pior['hora']}h ({ph_pior['winrate']}%)")

        # Insight de fingerprint
        fl2 = self._mem.get("fingerprint_loss",{})
        if fl2.get("total_losses_analisados",0) >= 10:
            hora_pior_loss = max(fl2.get("hora_mais_losses",{}).items(),
                                  key=lambda x:x[1], default=("?",0))
            if hora_pior_loss[0] != "?":
                partes_conclusao.append(
                    f"{hora_pior_loss[1]} losses às {hora_pior_loss[0]}h")

        conclusao = " | ".join(partes_conclusao) if partes_conclusao else (
            "Coletando dados para conclusões mais precisas..."
            if total < 50 else "Contexto analisado em 10 dimensões."
        )

        # ── Última conclusão aprendida ────────────────────────────
        conclusoes_rec = self._mem.get("conclusoes_aprendidas",[])
        conclusoes_txt = ""
        # Mostra as 2 mais recentes relevantes
        relevantes = [c for c in conclusoes_rec[-5:]
                      if c["tipo"] in ("cluster_loss","recuperacao","loss_score_alto")]
        if relevantes:
            ult = relevantes[-1]
            conclusoes_txt = f"\n💡 <i>{ult['msg']}</i>"

        # ── Monta bloco final ─────────────────────────────────────
        base_txt = (f"({total} entradas aprendidas)"
                    if total >= 20 else f"(aprendendo — {total}/20)")
        motivos_txt = "".join(f"  {emj} {txt}\n" for _,emj,txt in motivos)

        bloco = (
            f"{'─'*20}\n"
            f"🧠 <b>MenteViva</b> {base_txt}\n"
            f"{emoji_v} <b>{verd}</b>  <i>({pontos:+d} pts em 10 dimensões)</i>\n"
            f"\n<b>Análise:</b>\n{motivos_txt}"
            f"\n💬 <i>{conclusao}</i>"
            f"{calib_txt}"
            f"{conclusoes_txt}"
        )
        return bloco

    def resumo_rapido(self) -> str:
        """Resumo compacto para o comando /seca no Telegram."""
        d   = self._mem
        tot = d["meta"]["total_entradas"]
        if tot == 0:
            return "🧠 <b>MenteViva</b>: sem dados ainda."

        pn  = d["padroes_notaveis"]
        sv  = d["seca_no_sinal"].get("V", {})
        sp  = d["seca_no_sinal"].get("P", {})
        mom = d.get("momentum_recente", [])
        ult10 = mom[-10:] if len(mom) >= 10 else mom
        wr10  = sum(ult10)/len(ult10)*100 if ult10 else 0

        # Por score
        sc_txt = ""
        for k, v in d["por_score"].items():
            t = v["wins"]+v["losses"]
            if t >= 5:
                sc_txt += f"  {k}: {v['wins']}W/{v['losses']}L = {v['winrate']*100:.0f}%\n"

        # Calibração
        calib = d.get("calibracao", {})
        calib_txt = ""
        for verd, cv in calib.get("por_veredito", {}).items():
            if cv.get("total", 0) >= 5:
                calib_txt += f"  {verd}: {cv['wins']}/{cv['total']} = {cv['winrate']*100:.0f}%\n"

        return (
            f"🧠 <b>MenteViva</b> — {tot} entradas aprendidas\n\n"
            f"📊 <b>Por score:</b>\n{sc_txt}"
            f"\n🕐 Melhor hora: <b>{pn.get('melhor_hora',{}).get('hora','?')}h</b> "
            f"({pn.get('melhor_hora',{}).get('winrate',0):.0f}%) | "
            f"Pior: <b>{pn.get('pior_hora',{}).get('hora','?')}h</b> "
            f"({pn.get('pior_hora',{}).get('winrate',0):.0f}%)\n"
            f"\n🔄 Após 2 losses: "
            f"{d['pos_loss'].get('apos_2_loss',{}).get('wins',0)}/"
            f"{d['pos_loss'].get('apos_2_loss',{}).get('total',0)} wins = "
            f"{d['pos_loss'].get('apos_2_loss',{}).get('winrate',0)*100:.0f}%\n"
            f"\n🔥 Momentum (ult. 10): <b>{sum(ult10)}/{len(ult10)}</b> wins = {wr10:.0f}%\n"
            + (f"\n📐 <b>Calibração do veredito:</b>\n{calib_txt}" if calib_txt else "")
        )

    def registrar_resultado_veredito(self, verd: str, win: bool):
        """Calibração: registra se o veredito emitido acertou ou não."""
        calib = self._mem.get("calibracao",{})
        pv    = calib.get("por_veredito",{})
        if verd in pv:
            pv[verd]["total"] += 1
            if win: pv[verd]["wins"] += 1
            t = pv[verd]["total"]
            pv[verd]["winrate"] = round(pv[verd]["wins"]/t, 4)
            # Brier score: (prob_prevista - resultado)^2
            prob_map = {"EXCELENTE":0.90,"MUITO FAVORÁVEL":0.82,"FAVORÁVEL":0.72,
                        "NEUTRO-POSITIVO":0.62,"NEUTRO":0.50,"CAUTELA":0.38,"DESFAVORÁVEL":0.25}
            prob = prob_map.get(verd, 0.5)
            brier = (prob - (1 if win else 0)) ** 2
            pv[verd]["brier_sum"] = round(pv[verd].get("brier_sum",0) + brier, 4)
            calib["por_veredito"] = pv
            calib["amostras"]     = calib.get("amostras",0) + 1
            # Brier global (média)
            total_b = sum(v.get("brier_sum",0) for v in pv.values())
            total_n = sum(v.get("total",0) for v in pv.values())
            calib["brier_global"] = round(total_b/total_n, 4) if total_n else 0.0
            self._mem["calibracao"] = calib
            self._save()



# Instâncias globais dos 4 módulos
_kelly     = KellyCriterion()
_mente_viva = MenteViva()
_ev_calc   = ExpectedValueCalc()
_confusion = ConfusionMatrix()
_bootstrap = BootstrapValidator()
_sim_gale  = SimulacaoGale()


# ══════════════════════════════════════════════════════════════════
# MÓDULO — NumeroHoraFavorita
# Rastreia por número (0-14) em qual hora do dia ele aparece mais.
# Detecta quando um número está na sua "hora favorita" e avisa.
# Salva em: numero_hora_favorita.json
# ══════════════════════════════════════════════════════════════════

class NumeroHoraFavorita:
    """
    Para cada número do Double (0 a 14), registra quantas vezes
    apareceu em cada hora do dia (00h–23h).

    Calcula:
      - hora favorita de cada número (hora com mais aparições)
      - fator de concentração: aparições_hora / média_por_hora
        → fator > 2.0 = número aparece 2× mais nessa hora
      - alerta quando estamos NA hora favorita de algum número

    Salva histórico em numero_hora_favorita.json
    """
    DB_FILE = "numero_hora_favorita.json"
    NUMEROS = list(range(15))   # 0 a 14

    def __init__(self):
        # {numero: {hora_str: contagem}}
        self._contagens: dict = {str(n): {} for n in self.NUMEROS}
        self._total_por_numero: dict = {str(n): 0 for n in self.NUMEROS}
        self._ultima_atualizacao: str = ""
        self._load()

    def _load(self):
        if os.path.exists(self.DB_FILE):
            try:
                with open(self.DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._contagens = data.get("contagens", {str(n): {} for n in self.NUMEROS})
                self._total_por_numero = data.get("totais", {str(n): 0 for n in self.NUMEROS})
                total = sum(self._total_por_numero.values())
                log.info(f"NumeroHoraFavorita: carregado ({total} registros)")
            except Exception as e:
                log.error(f"NumeroHoraFavorita load: {e}")

    def _save(self):
        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "contagens": self._contagens,
                    "totais": self._total_por_numero,
                    "ultima_atualizacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"NumeroHoraFavorita save: {e}")

    def registrar(self, numero: int) -> None:
        """Registra uma aparição do número na hora atual."""
        hora = datetime.now().strftime("%H")
        k = str(numero)
        if k not in self._contagens:
            self._contagens[k] = {}
        self._contagens[k][hora] = self._contagens[k].get(hora, 0) + 1
        self._total_por_numero[k] = self._total_por_numero.get(k, 0) + 1
        self._save()

    def registrar_historico(self, historico: list) -> None:
        """
        Alimenta com histórico completo: lista de {'roll': int, 'hora': 'HH'}.
        Usado na carga inicial para ter dados desde o início.
        """
        for item in historico:
            roll = item.get("roll")
            hora = item.get("hora")
            if roll is None or hora is None:
                continue
            k = str(roll)
            if k not in self._contagens:
                self._contagens[k] = {}
            self._contagens[k][hora] = self._contagens[k].get(hora, 0) + 1
            self._total_por_numero[k] = self._total_por_numero.get(k, 0) + 1
        self._save()
        total = sum(self._total_por_numero.values())
        log.info(f"NumeroHoraFavorita: histórico carregado ({total} registros)")

    def hora_favorita(self, numero: int) -> dict:
        """
        Retorna a hora favorita do número e o fator de concentração.
        Fator = aparições_na_hora / média_por_hora
        """
        k = str(numero)
        contagens = self._contagens.get(k, {})
        total = self._total_por_numero.get(k, 0)
        if not contagens or total < 10:
            return {"hora": None, "contagem": 0, "fator": 0.0, "total": total}

        media_por_hora = total / 24
        melhor_hora = max(contagens, key=contagens.get)
        melhor_cnt  = contagens[melhor_hora]
        fator = round(melhor_cnt / media_por_hora, 2) if media_por_hora > 0 else 0.0

        return {
            "hora":     melhor_hora,
            "contagem": melhor_cnt,
            "fator":    fator,
            "total":    total,
            "media":    round(media_por_hora, 1),
        }

    def top_numeros_hora_atual(self, top_n: int = 5) -> list:
        """
        Retorna os N números com maior concentração NA HORA ATUAL.
        Ou seja: quais números estão na sua "hora favorita" agora.
        """
        hora_atual = datetime.now().strftime("%H")
        resultados = []
        for numero in self.NUMEROS:
            k = str(numero)
            contagens = self._contagens.get(k, {})
            total = self._total_por_numero.get(k, 0)
            if total < 10:
                continue
            cnt_hora = contagens.get(hora_atual, 0)
            media_por_hora = total / 24
            fator = round(cnt_hora / media_por_hora, 2) if media_por_hora > 0 else 0.0
            resultados.append({
                "numero":   numero,
                "hora":     hora_atual,
                "contagem": cnt_hora,
                "fator":    fator,
                "total":    total,
            })
        resultados.sort(key=lambda x: x["fator"], reverse=True)
        return resultados[:top_n]

    def linha_alerta_hora_atual(self) -> str:
        """
        Retorna linha de alerta se algum número estiver na hora pico (fator ≥ 1.8).
        """
        hora_atual = datetime.now().strftime("%H")
        top = self.top_numeros_hora_atual(top_n=3)
        alertas = [r for r in top if r["fator"] >= 1.8]
        if not alertas:
            return ""
        partes = []
        for r in alertas:
            partes.append(
                f"N{r['numero']} ({r['fator']}×)"
            )
        return (
            f"🕐 <b>Hora favorita ativa {hora_atual}h:</b> "
            f"{', '.join(partes)} — aparecem mais agora"
        )

    def resumo_numero(self, numero: int) -> str:
        """Resumo completo de um número específico."""
        k = str(numero)
        hf = self.hora_favorita(numero)
        if not hf["hora"]:
            return f"🔢 N{numero}: dados insuficientes (mín. 10 aparições)"
        contagens = self._contagens.get(k, {})
        # Top 3 horas
        top3 = sorted(contagens.items(), key=lambda x: x[1], reverse=True)[:3]
        top3_txt = " | ".join(f"{h}h:{c}×" for h, c in top3)
        hora_atual = datetime.now().strftime("%H")
        cnt_agora = contagens.get(hora_atual, 0)
        media = hf["media"]
        agora_fator = round(cnt_agora / media, 2) if media > 0 else 0.0
        if agora_fator >= 1.8:
            agora_emoji = "🔥"
            agora_txt = f"hora pico! ({agora_fator}×)"
        elif agora_fator >= 1.0:
            agora_txt = f"normal ({agora_fator}×)"
            agora_emoji = "🟡"
        else:
            agora_txt = f"fraco ({agora_fator}×)"
            agora_emoji = "🔵"
        return (
            f"🔢 <b>Número {numero}</b>\n"
            f"   Total aparições: <b>{hf['total']}</b> | Média/hora: <b>{hf['media']:.1f}</b>\n"
            f"   Hora favorita: <b>{hf['hora']}h</b> ({hf['contagem']}× | {hf['fator']}× a média)\n"
            f"   Top 3 horas: <b>{top3_txt}</b>\n"
            f"   Agora ({hora_atual}h): {agora_emoji} <b>{agora_txt}</b>"
        )

    def resumo_geral(self) -> str:
        """Top 5 números mais concentrados na hora atual."""
        hora_atual = datetime.now().strftime("%H")
        top5 = self.top_numeros_hora_atual(top_n=5)
        if not top5:
            return "🕐 <b>Hora Favorita</b>: dados insuficientes ainda."
        linhas = []
        for i, r in enumerate(top5, 1):
            emoji = "🔥" if r["fator"] >= 1.8 else ("🟡" if r["fator"] >= 1.0 else "🔵")
            linhas.append(
                f"  {i}. N{r['numero']}  {emoji} <b>{r['fator']}×</b> a média "
                f"({r['contagem']} vez{'es' if r['contagem'] != 1 else ''} nessa hora)"
            )
        return (
            f"🕐 <b>Hora Favorita — {hora_atual}h</b>\n"
            f"Top 5 números mais ativos agora:\n"
            + "\n".join(linhas)
        )


# Instância global
_numero_hora = NumeroHoraFavorita()


# Calcula entropia de Shannon da sequência VP recente.
# Alta entropia = mercado caótico = maior incerteza = bloqueia sinal.
# ══════════════════════════════════════════════════════════════════

class EntropiaHashGuard:
    """
    Usa a entropia de Shannon da sequência VP recente como proxy da
    "qualidade" do hash atual. Quando a entropia está alta (sequência
    muito aleatória), o roll gerado pelo HMAC-SHA256 tem maior
    dispersão e os padrões históricos têm menos poder preditivo.

    Fórmula: H = -Σ p(x) × log2(p(x))  para x ∈ {V, P}
    Normalizada: H_norm = H / log2(2) → [0, 1]
    H_norm próximo de 1 → sequência maximamente aleatória → bloqueia
    H_norm abaixo do limiar → sequência tem viés → sinal permitido
    """

    def calcular(self, history: list) -> float:
        """Retorna entropia normalizada [0..1] das últimas N rodadas VP."""
        vp = [c for c in history if c in ("V", "P")][-ENTROPIA_HASH_JANELA:]
        if len(vp) < 4:
            return 0.5   # fallback neutro
        total = len(vp)
        v = vp.count("V") / total
        p = vp.count("P") / total
        ent = 0.0
        for prob in (v, p):
            if prob > 0:
                ent -= prob * math.log2(prob)
        return round(ent / math.log2(2), 4)   # normaliza para [0..1]

    def deve_bloquear(self, history: list) -> tuple[bool, float]:
        """
        Retorna (deve_bloquear, entropia).
        Bloqueia se H_norm > ENTROPIA_HASH_LIMIAR.
        """
        h = self.calcular(history)
        return h > ENTROPIA_HASH_LIMIAR, h

    def linha_status(self, history: list) -> str:
        h = self.calcular(history)
        if h > ENTROPIA_HASH_LIMIAR:
            emoji = "🔴"
            texto = "caótico — sinal bloqueado"
        elif h > 0.80:
            emoji = "🟠"
            texto = "elevada"
        elif h > 0.65:
            emoji = "🟡"
            texto = "moderada"
        else:
            emoji = "🟢"
            texto = "baixa — mercado previsível"
        return f"🎲 Entropia: {emoji} <b>{h:.3f}</b> ({texto})"


# ══════════════════════════════════════════════════════════════════
# FILTRO 2 — AutoCorrelacaoPearson
# Correlação de Pearson entre sequência VP recente e previsão.
# Baixa correlação = padrão não está alinhado com o momento atual.
# ══════════════════════════════════════════════════════════════════

class AutoCorrelacaoPearson:
    """
    Calcula a correlação de Pearson entre:
      X = sequência binária das últimas AUTOCORR_JANELA rodadas VP
          (V=1, P=0) convertida em vetor
      Y = vetor "ideal" que seria a previsão do padrão ativo se
          aplicado retrospectivamente nas mesmas posições

    Correlação alta (≥ AUTOCORR_LIMIAR):
        A sequência atual está alinhada com o padrão → sinal confiável.
    Correlação baixa (< AUTOCORR_LIMIAR):
        A sequência diverge do esperado pelo padrão → descarta sinal.

    Na prática: testa se as últimas N rodadas "se comportam" como o
    padrão prevê, antes de emitir sinal para a próxima rodada.
    """

    @staticmethod
    def _encode(cores: list) -> list:
        """Converte lista de cores em vetor binário (V=1, P=0)."""
        return [1 if c == "V" else 0 for c in cores]

    def calcular(self, history: list, pattern: list, prediction: str) -> float:
        """
        Retorna coeficiente de Pearson [-1, 1].
        Usa as últimas AUTOCORR_JANELA rodadas VP como X
        e o padrão [pattern + prediction] repetido como Y.
        """
        vp = [c for c in history if c in ("V", "P")][-AUTOCORR_JANELA:]
        if len(vp) < AUTOCORR_MIN_AMOSTRAS:
            return 1.0   # sem dados suficientes: não bloqueia

        x = self._encode(vp)
        # Gera vetor Y: repete o padrão + previsão ciclicamente
        template = self._encode(list(pattern) + [prediction])
        if not template:
            return 1.0
        n = len(x)
        y = [template[i % len(template)] for i in range(n)]

        # Pearson: r = Σ((xi-μx)(yi-μy)) / (σx × σy × n)
        mx = sum(x) / n
        my = sum(y) / n
        num   = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        den_x = math.sqrt(sum((xi - mx) ** 2 for xi in x))
        den_y = math.sqrt(sum((yi - my) ** 2 for yi in y))
        if den_x == 0 or den_y == 0:
            return 0.0
        return round(num / (den_x * den_y), 4)

    def deve_bloquear(self, history: list,
                      pattern: list, prediction: str) -> tuple[bool, float]:
        """
        Retorna (deve_bloquear, correlacao).
        Bloqueia se correlação < AUTOCORR_LIMIAR.
        """
        r = self.calcular(history, pattern, prediction)
        return r < AUTOCORR_LIMIAR, r

    def linha_status(self, r: float) -> str:
        if r >= AUTOCORR_LIMIAR:
            emoji = "🟢"
            texto = "alinhado"
        elif r >= 0.20:
            emoji = "🟡"
            texto = "baixo"
        else:
            emoji = "🔴"
            texto = "divergente"
        return f"📐 Autocorr: {emoji} <b>{r:+.3f}</b> ({texto})"


# ══════════════════════════════════════════════════════════════════
# FILTRO 3 — BiasPósBranco
# Após branco, as próximas rodadas têm viés para a cor oposta
# à que saiu imediatamente antes do branco.
# ══════════════════════════════════════════════════════════════════

class BiasPósBranco:
    """
    Observação empírica no histórico da Blaze:
    Após um resultado branco (tile 0), existe viés estatístico
    para que as próximas BIAS_POS_BRANCO_JANELA rodadas sigam
    a cor oposta à que saiu antes do branco.

    Exemplo: ...V V B [próximas] → viés para P
             ...P P B [próximas] → viés para V

    O filtro usa essa informação para:
    a) Confirmar sinais que estão alinhados com o viés → bônus de score
    b) Bloquear sinais que vão contra o viés → cancela

    O viés se dissipa após BIAS_POS_BRANCO_JANELA rodadas VP.
    """

    def __init__(self):
        self._cor_antes_branco: Optional[str] = None   # V ou P
        self._rodadas_desde_branco: int        = 0     # contador

    def atualizar(self, history_buffer: list) -> None:
        """
        Atualiza estado interno a cada rodada completa.
        Detecta se o último resultado foi branco e registra
        a cor VP imediatamente anterior ao branco.
        """
        if not history_buffer:
            return

        ultimo = history_buffer[-1]

        if ultimo == "B":
            # Encontra a cor VP mais recente antes do branco
            for c in reversed(history_buffer[:-1]):
                if c in ("V", "P"):
                    self._cor_antes_branco    = c
                    self._rodadas_desde_branco = 0
                    log.info(
                        f"⚪ BRANCO detectado | cor antes: {c} | "
                        f"bias → {'P' if c == 'V' else 'V'} "
                        f"por {BIAS_POS_BRANCO_JANELA} rodadas"
                    )
                    return
            # Sem VP antes do branco
            self._cor_antes_branco = None
        elif ultimo in ("V", "P"):
            if self._cor_antes_branco is not None:
                self._rodadas_desde_branco += 1
                if self._rodadas_desde_branco >= BIAS_POS_BRANCO_JANELA:
                    # Janela expirou
                    self._cor_antes_branco    = None
                    self._rodadas_desde_branco = 0

    @property
    def bias_ativo(self) -> bool:
        return (
            BIAS_POS_BRANCO_ATIVO and
            self._cor_antes_branco is not None and
            self._rodadas_desde_branco < BIAS_POS_BRANCO_JANELA
        )

    @property
    def cor_favorecida(self) -> Optional[str]:
        """Retorna a cor favorecida pelo bias (oposta à que saiu antes do branco)."""
        if not self.bias_ativo:
            return None
        return "P" if self._cor_antes_branco == "V" else "V"

    def avaliar_sinal(self, prediction: str) -> tuple[str, str]:
        """
        Avalia um sinal à luz do bias pós-branco.
        Retorna (status, motivo):
          'confirma' — sinal alinhado com o bias
          'bloqueia' — sinal contra o bias
          'neutro'   — bias não ativo
        """
        if not self.bias_ativo:
            return "neutro", ""
        favorecida = self.cor_favorecida
        restantes  = BIAS_POS_BRANCO_JANELA - self._rodadas_desde_branco
        emoji_fav  = COLOR_LETTER_TO_EMOJI.get(favorecida, "?")
        emoji_ant  = COLOR_LETTER_TO_EMOJI.get(self._cor_antes_branco, "?")
        if prediction == favorecida:
            return "confirma", (
                f"⚪ Bias pós-branco ✅ — favorece {emoji_fav} "
                f"({restantes} rod. restantes, antes={emoji_ant})"
            )
        else:
            return "bloqueia", (
                f"⚪ Bias pós-branco ❌ — sinal contra o bias "
                f"({emoji_fav} favorecida, {restantes} rod. restantes)"
            )

    def linha_status(self) -> str:
        if not self.bias_ativo:
            return "⚪ Bias pós-branco: <i>inativo</i>"
        fav = self.cor_favorecida
        emoji_fav = COLOR_LETTER_TO_EMOJI.get(fav, "?")
        restantes = BIAS_POS_BRANCO_JANELA - self._rodadas_desde_branco
        return (
            f"⚪ Bias pós-branco: 🟡 <b>ATIVO</b> → {emoji_fav} "
            f"(<b>{restantes}</b> rod. restantes)"
        )


# ══════════════════════════════════════════════════════════════════
# REGIME DETECTOR — Detecta o "clima" atual do jogo
# ══════════════════════════════════════════════════════════════════

class RegimeDetector:
    """
    Detecta o regime atual do mercado a partir das últimas REGIME_JANELA
    cores VP e ajusta a estratégia de seleção de padrões:

    Regimes:
      • trending    — uma cor domina (>= 65% das últimas 20)
                      → favorecer padrões de continuação (cluster)
      • alternating — troca frequente entre V e P (alternâncias >= 65%)
                      → favorecer padrões de reversão / alternância
      • chaotic     — nenhum padrão dominante; entropia alta
                      → aumentar score mínimo, reduzir exposição

    A decisão é baseada em dois sub-índices:
      dominance_ratio  = max(count_V, count_P) / total
      alternation_rate = trocas / (total - 1)
    """

    REGIMES = ("trending", "alternating", "chaotic")

    def __init__(self):
        self._regime: str   = "chaotic"
        self._confianca: float = 0.0
        self._dominante: Optional[str] = None
        self._historico_regimes: list  = []   # últimos 10 regimes detectados

    def atualizar(self, history: list) -> None:
        vp = [c for c in history if c in ("V", "P")][-REGIME_JANELA:]
        if len(vp) < 6:
            self._regime    = "chaotic"
            self._confianca = 0.0
            return

        total = len(vp)
        v_count = vp.count("V")
        p_count = vp.count("P")
        dominance_ratio = max(v_count, p_count) / total
        self._dominante = "V" if v_count > p_count else "P"

        trocas = sum(1 for i in range(1, len(vp)) if vp[i] != vp[i-1])
        alternation_rate = trocas / (total - 1) if total > 1 else 0.5

        # Entropia normalizada
        ent = 0.0
        for c in ("V", "P"):
            p = vp.count(c) / total
            if p > 0:
                ent -= p * math.log2(p)
        ent_norm = ent / math.log2(2)

        prev_regime = self._regime

        if dominance_ratio >= REGIME_CONF_MIN:
            self._regime    = "trending"
            self._confianca = round(dominance_ratio, 3)
        elif alternation_rate >= REGIME_CONF_MIN:
            self._regime    = "alternating"
            self._confianca = round(alternation_rate, 3)
        else:
            self._regime    = "chaotic"
            self._confianca = round(1.0 - abs(dominance_ratio - alternation_rate), 3)

        # Registra transição de regime
        if self._regime != prev_regime:
            self._historico_regimes.append({
                "de": prev_regime,
                "para": self._regime,
                "hora": datetime.now().strftime("%H:%M"),
            })
            if len(self._historico_regimes) > 10:
                self._historico_regimes = self._historico_regimes[-10:]
            log.info(
                f"🌊 REGIME VP: {prev_regime} → {self._regime} "
                f"(conf={self._confianca:.0%} | dom={dominance_ratio:.0%} | alt={alternation_rate:.0%})"
            )

    @property
    def regime(self) -> str:
        return self._regime

    @property
    def confianca(self) -> float:
        return self._confianca

    @property
    def dominante(self) -> Optional[str]:
        return self._dominante

    def score_bonus(self) -> int:
        """Retorna bônus/penalidade de score baseado no regime."""
        if self._regime == "trending":    return +8
        if self._regime == "alternating": return +5
        return -10  # chaotic

    def score_minimo_override(self, score_base: int) -> int:
        """No regime caótico, exige score mais alto."""
        if self._regime == "chaotic":
            return max(score_base, 45)
        return score_base

    def filtra_padrao(self, pattern: list, prediction: str) -> tuple[bool, str]:
        """
        Verifica se o padrão é coerente com o regime atual.
        Retorna (aprovado, motivo).

        Lógica:
          - trending + prediction != dominante → penaliza (mas não bloqueia hardcoded,
            deixa o score decidir) → retorna False se conf >= 0.75
          - alternating: verifica se o padrão termina com reversão
          - chaotic: sempre passa (score alto já filtra)
        """
        if len(pattern) < 2:
            return True, ""

        ultima_cor = pattern[-1]

        if self._regime == "trending" and self._confianca >= 0.75:
            # Em tendência forte: padrões que apostam contra a tendência são suspeitos
            if prediction != self._dominante:
                return False, (
                    f"🌊 Regime <b>TRENDING</b> ({COLOR_LETTER_TO_EMOJI.get(self._dominante,'?')} "
                    f"{self._confianca:.0%}) — padrão contra-tendência bloqueado"
                )

        if self._regime == "alternating" and self._confianca >= 0.70:
            # Em alternância: o padrão deve prever a cor OPOSTA à última
            cor_oposta = "P" if ultima_cor == "V" else "V"
            if prediction != cor_oposta:
                return False, (
                    f"🌊 Regime <b>ALTERNATING</b> ({self._confianca:.0%}) — "
                    f"padrão de continuação bloqueado (espera reversão)"
                )

        return True, ""

    def emoji_regime(self) -> str:
        emap = {"trending": "📈", "alternating": "🔄", "chaotic": "🌀"}
        return emap.get(self._regime, "❓")

    def linha_status(self) -> str:
        emoji = self.emoji_regime()
        dom_str = ""
        if self._regime == "trending" and self._dominante:
            dom_str = f" {COLOR_LETTER_TO_EMOJI.get(self._dominante,'')}"
        return (
            f"🌊 Regime: {emoji} <b>{self._regime.upper()}{dom_str}</b> "
            f"({self._confianca:.0%})"
        )

    def to_dict(self) -> dict:
        return {
            "regime": self._regime,
            "confianca": self._confianca,
            "dominante": self._dominante,
            "historico": self._historico_regimes,
        }

    def from_dict(self, data: dict) -> None:
        self._regime    = data.get("regime", "chaotic")
        self._confianca = data.get("confianca", 0.0)
        self._dominante = data.get("dominante")
        self._historico_regimes = data.get("historico", [])


# ══════════════════════════════════════════════════════════════════
# AUTO-BET — Autenticação e apostas automáticas na Blaze
# ══════════════════════════════════════════════════════════════════

@dataclass
class AutoBetConfig:
    ativo:       bool  = False
    dry_run:     bool  = True
    aposta_base: float = 20.0
    max_niveis:  int   = 3
    stop_loss:   float = 100.0
    take_profit: float = 200.0

    @classmethod
    def from_ini(cls, cfg: configparser.ConfigParser) -> "AutoBetConfig":
        if not cfg.has_section("autobet"):
            return cls()
        return cls(
            ativo       = cfg.getboolean("autobet", "ativo",        fallback=False),
            dry_run     = cfg.getboolean("autobet", "dry_run",      fallback=True),
            aposta_base = cfg.getfloat("autobet",   "aposta_base",  fallback=20.0),
            max_niveis  = cfg.getint("autobet",     "max_niveis",   fallback=3),
            stop_loss   = cfg.getfloat("autobet",   "stop_loss",    fallback=100.0),
            take_profit = cfg.getfloat("autobet",   "take_profit",  fallback=200.0),
        )


class BlazeAutobet:
    """
    Gerencia autenticação e apostas automáticas na Blaze.

    Progressão Paroli (positiva):
      nível 1 → aposta_base × 1
      nível 2 → aposta_base × 2  (após 1 win)
      nível 3 → aposta_base × 4  (após 2 wins seguidos)
      qualquer LOSS → reset para nível 1

    stop_loss  → pausa sessão se perda acumulada ≥ stop_loss
    take_profit → pausa sessão se lucro acumulado ≥ take_profit
    """

    _AUTH_ENDPOINT  = "/api/auth/local"
    _BET_ENDPOINT   = "/api/singleplayer-originals/originals/roulette_games/bets"
    _BAL_ENDPOINT   = "/api/wallet"

    def __init__(self, base_url: str, email: str, password: str,
                 cfg: AutoBetConfig, session_getter):
        self.base_url       = base_url.rstrip("/")
        self.email          = email
        self.password       = password
        self.cfg            = cfg
        self._get_session   = session_getter

        self._token: Optional[str] = None
        self._token_ts: float      = 0.0
        self._token_ttl: float     = 3500.0

        self._nivel_atual:    int   = 1
        self._wins_seguidos:  int   = 0

        self._saldo_inicio:   float = 0.0
        self._pnl_sessao:     float = 0.0
        self._pausado:        bool  = False
        self._motivo_pausa:   str   = ""

        self._ultimo_bet_id:  Optional[str] = None

    def _get_aposta_nivel(self) -> float:
        fator = 2 ** (self._nivel_atual - 1)
        return round(self.cfg.aposta_base * fator, 2)

    def _url(self, endpoint: str) -> str:
        return self.base_url + endpoint

    async def _session(self) -> aiohttp.ClientSession:
        return await self._get_session()

    async def ensure_token(self) -> bool:
        if self._token and (time.time() - self._token_ts) < self._token_ttl:
            return True
        return await self._login()

    async def _login(self) -> bool:
        try:
            sess = await self._session()
            async with sess.post(
                self._url(self._AUTH_ENDPOINT),
                json={"username": self.email, "password": self.password},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                data = await r.json()
                if r.status == 200 and data.get("access_token"):
                    self._token    = data["access_token"]
                    self._token_ts = time.time()
                    log.info("✅ BlazeAutobet: login OK")
                    return True
                log.error(f"❌ BlazeAutobet login falhou: status={r.status} | {data}")
                return False
        except Exception as e:
            log.error(f"❌ BlazeAutobet login exception: {e}")
            return False

    async def get_balance(self) -> Optional[float]:
        if not await self.ensure_token():
            return None
        try:
            sess = await self._session()
            async with sess.get(
                self._url(self._BAL_ENDPOINT),
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    if isinstance(data, list):
                        for w in data:
                            if w.get("currency", "").upper() in ("BRL", "R$"):
                                return float(w.get("balance", 0))
                        if data:
                            return float(data[0].get("balance", 0))
                    if isinstance(data, dict):
                        return float(data.get("balance", data.get("amount", 0)))
        except Exception as e:
            log.warning(f"BlazeAutobet get_balance: {e}")
        return None

    async def place_bet(self, color: str) -> dict:
        if self._pausado:
            return {"ok": False, "motivo": f"Sessão pausada: {self._motivo_pausa}",
                    "valor": 0, "nivel": self._nivel_atual, "dry_run": self.cfg.dry_run}

        if color not in ("V", "P"):
            return {"ok": False, "motivo": f"Cor inválida: {color}",
                    "valor": 0, "nivel": self._nivel_atual, "dry_run": self.cfg.dry_run}

        valor = self._get_aposta_nivel()
        color_api = COLOR_LETTER_TO_API[color]

        if self.cfg.dry_run:
            log.info(f"[DRY-RUN] Aposta simulada: {color} | R${valor:.2f} | nível {self._nivel_atual}")
            self._ultimo_bet_id = f"DRY-{int(time.time())}"
            return {"ok": True, "valor": valor, "nivel": self._nivel_atual,
                    "dry_run": True, "bet_id": self._ultimo_bet_id, "motivo": ""}

        if not await self.ensure_token():
            return {"ok": False, "motivo": "Falha no login Blaze",
                    "valor": valor, "nivel": self._nivel_atual, "dry_run": False}

        payload = {
            "color":         color_api,
            "amount":        valor,
            "currency_type": "BRL",
        }
        try:
            sess = await self._session()
            async with sess.post(
                self._url(self._BET_ENDPOINT),
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type":  "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                data = await r.json()
                if r.status in (200, 201):
                    bet_id = str(data.get("id", ""))
                    self._ultimo_bet_id = bet_id
                    log.info(
                        f"✅ BlazeAutobet BET OK | cor={color} | "
                        f"R${valor:.2f} | nível={self._nivel_atual} | id={bet_id}"
                    )
                    return {"ok": True, "valor": valor, "nivel": self._nivel_atual,
                            "dry_run": False, "bet_id": bet_id, "motivo": ""}
                else:
                    motivo = data.get("message", data.get("error", str(data)))
                    log.error(f"❌ BlazeAutobet BET FALHOU | status={r.status} | {motivo}")
                    if r.status in (401, 403):
                        self._token = None
                    return {"ok": False, "motivo": motivo,
                            "valor": valor, "nivel": self._nivel_atual, "dry_run": False}
        except Exception as e:
            log.error(f"❌ BlazeAutobet place_bet exception: {e}")
            return {"ok": False, "motivo": str(e),
                    "valor": valor, "nivel": self._nivel_atual, "dry_run": False}

    def register_result(self, win: bool, valor_apostado: float) -> dict:
        if win:
            lucro = valor_apostado * 1.0
            self._pnl_sessao   += lucro
            self._wins_seguidos += 1
            if self._wins_seguidos >= self.cfg.max_niveis:
                self._nivel_atual    = 1
                self._wins_seguidos  = 0
                log.info(f"🏆 Paroli: topo ({self.cfg.max_niveis} wins) → reset nível 1")
            else:
                self._nivel_atual = min(self._nivel_atual + 1, self.cfg.max_niveis)
                log.info(f"📈 Paroli: WIN → nível {self._nivel_atual}")
        else:
            self._pnl_sessao   -= valor_apostado
            self._nivel_atual   = 1
            self._wins_seguidos = 0
            log.info(f"📉 Paroli: LOSS → reset nível 1 | PnL sessão: R${self._pnl_sessao:.2f}")

        if self._pnl_sessao <= -abs(self.cfg.stop_loss):
            self._pausado      = True
            self._motivo_pausa = f"STOP LOSS atingido (R${self._pnl_sessao:.2f})"
            log.warning(f"🛑 {self._motivo_pausa}")
        elif self._pnl_sessao >= self.cfg.take_profit:
            self._pausado      = True
            self._motivo_pausa = f"TAKE PROFIT atingido (R${self._pnl_sessao:.2f})"
            log.info(f"🎯 {self._motivo_pausa}")

        return {
            "nivel_proximo": self._nivel_atual,
            "aposta_proxima": self._get_aposta_nivel(),
            "pnl_sessao":    self._pnl_sessao,
            "wins_seguidos": self._wins_seguidos,
            "pausado":       self._pausado,
            "motivo_pausa":  self._motivo_pausa,
        }

    def reset_sessao(self) -> None:
        self._pausado        = False
        self._motivo_pausa   = ""
        self._pnl_sessao     = 0.0
        self._nivel_atual    = 1
        self._wins_seguidos  = 0
        log.info("🔄 BlazeAutobet: sessão reiniciada")

    def status_line(self) -> str:
        modo = "🔵 DRY-RUN" if self.cfg.dry_run else "🟢 BANCA REAL"
        pausa = f"  ⛔ {self._motivo_pausa}" if self._pausado else ""
        sinal_pnl = "+" if self._pnl_sessao >= 0 else ""
        return (
            f"🎰 <b>AutoBet</b> {modo}{pausa}\n"
            f"   💰 Próxima: <b>R$ {self._get_aposta_nivel():.2f}</b> "
            f"(Nível {self._nivel_atual} | {self._wins_seguidos}🔥 seguidos)\n"
            f"   📊 PnL sessão: <b>{sinal_pnl}R$ {self._pnl_sessao:.2f}</b> "
            f"| Stop: R${self.cfg.stop_loss:.0f} | Gain: R${self.cfg.take_profit:.0f}"
        )


# ══════════════════════════════════════════════════════════════════
# MOTOR DE DECISÃO VP
# ══════════════════════════════════════════════════════════════════

class MotorDecisaoVP:
    JANELA_TENDENCIA = 10
    JANELA_CURTA     = 5
    JANELA_RSI       = 14
    MIN_CONFIANCA      = 0.55
    MIN_SCORE_AUTONOMO = 70

    def analisar(self, history: list) -> dict:
        vp = [c for c in history if c in ("V", "P")]
        if len(vp) < 15:
            return self._indeciso("histórico insuficiente (mínimo 15 rodadas VP)")

        pontos_v = 0.0
        pontos_p = 0.0
        motivos  = []
        detalhes = {}

        tend = self._tendencia(vp)
        detalhes["tendencia"] = tend
        if tend["dominante"]:
            peso = 25 if tend["forca"] == "forte" else (15 if tend["forca"] == "moderada" else 8)
            if tend["dominante"] == "V":
                pontos_v += peso
            else:
                pontos_p += peso
            dom_e = COLOR_LETTER_TO_EMOJI.get(tend["dominante"], "?")
            motivos.append(
                f"📊 Tendência {dom_e} {tend['forca']} "
                f"({tend['v10']}🔴 / {tend['p10']}⚫ últimas 10)"
            )
        else:
            motivos.append(f"📊 Tendência equilibrada ({tend['v10']}🔴 / {tend['p10']}⚫)")

        rsi_v = self._rsi(vp, alvo="V")
        rsi_p = self._rsi(vp, alvo="P")
        detalhes["rsi_v"] = rsi_v
        detalhes["rsi_p"] = rsi_p
        if rsi_v >= 70:
            pontos_p += 20
            motivos.append(f"📈 RSI Vermelho sobrecomprado ({rsi_v:.0f}) → reversão ⚫️")
        elif rsi_v <= 30:
            pontos_v += 20
            motivos.append(f"📈 RSI Vermelho sobrevendido ({rsi_v:.0f}) → retorno 🔴")
        elif rsi_p >= 70:
            pontos_v += 20
            motivos.append(f"📈 RSI Preto sobrecomprado ({rsi_p:.0f}) → reversão 🔴")
        elif rsi_p <= 30:
            pontos_p += 20
            motivos.append(f"📈 RSI Preto sobrevendido ({rsi_p:.0f}) → retorno ⚫️")
        else:
            motivos.append(f"📈 RSI neutro (🔴{rsi_v:.0f} ⚫{rsi_p:.0f})")

        cluster = self._cluster(vp)
        detalhes["cluster"] = cluster
        if cluster["tamanho"] >= 4:
            oposto = "P" if cluster["cor"] == "V" else "V"
            peso   = min(25, cluster["tamanho"] * 5)
            if oposto == "V":
                pontos_v += peso
            else:
                pontos_p += peso
            c_e = COLOR_LETTER_TO_EMOJI.get(cluster["cor"], "?")
            o_e = COLOR_LETTER_TO_EMOJI.get(oposto, "?")
            motivos.append(f"🔗 Cluster {c_e}×{cluster['tamanho']} → reversão {o_e} esperada")
        elif cluster["tamanho"] >= 2:
            if cluster["cor"] == "V":
                pontos_v += 8
            else:
                pontos_p += 8
            c_e = COLOR_LETTER_TO_EMOJI.get(cluster["cor"], "?")
            motivos.append(f"🔗 Cluster {c_e}×{cluster['tamanho']} — continuação possível")

        markov = self._markov(vp, order=3)
        detalhes["markov"] = markov
        if markov and markov["confianca"] >= 0.60:
            peso = int(markov["confianca"] * 20)
            if markov["previsao"] == "V":
                pontos_v += peso
            else:
                pontos_p += peso
            mk_e = COLOR_LETTER_TO_EMOJI.get(markov["previsao"], "?")
            motivos.append(
                f"🧮 Markov VP → {mk_e} ({markov['confianca']:.0%}, {markov['amostras']} amostras)"
            )

        alt = self._alternancia(vp)
        detalhes["alternancia"] = alt
        if alt["alternando"] and alt["ultima"] in ("V", "P"):
            oposto_alt = "P" if alt["ultima"] == "V" else "V"
            if oposto_alt == "V":
                pontos_v += 10
            else:
                pontos_p += 10
            u_e = COLOR_LETTER_TO_EMOJI.get(alt["ultima"], "?")
            o_e = COLOR_LETTER_TO_EMOJI.get(oposto_alt, "?")
            motivos.append(f"🔄 Alternância detectada (última: {u_e}) → aposta {o_e}")

        ent = self._entropia(vp)
        detalhes["entropia"] = ent
        if ent < 0.50:
            motivos.append(f"🎯 Entropia baixa ({ent:.2f}) — mercado travado, tendência dominante")
        elif ent > 0.90:
            motivos.append(f"⚠️ Entropia alta ({ent:.2f}) — mercado caótico, cautela redobrada")
        else:
            motivos.append(f"✅ Entropia ({ent:.2f}) — mercado previsível")

        total_pts = pontos_v + pontos_p
        if total_pts == 0:
            return self._indeciso("sem pontuação — mercado sem padrão claro")

        conf_v = pontos_v / total_pts
        conf_p = pontos_p / total_pts

        if conf_v >= self.MIN_CONFIANCA:
            decisao   = "V"
            confianca = conf_v
        elif conf_p >= self.MIN_CONFIANCA:
            decisao   = "P"
            confianca = conf_p
        else:
            return self._indeciso(
                f"baixa confiança (🔴{conf_v:.0%} ⚫{conf_p:.0%}) — aguardando sinal mais claro"
            )

        indicadores_ok = sum([
            1 if (decisao == "V" and tend.get("dominante") == "V") or
                 (decisao == "P" and tend.get("dominante") == "P") else 0,
            1 if (decisao == "V" and detalhes.get("rsi_v", 50) <= 30) or
                 (decisao == "P" and detalhes.get("rsi_p", 50) <= 30) else 0,
            1 if cluster.get("cor") == decisao and cluster.get("tamanho", 0) >= 2 else 0,
            1 if markov and markov.get("previsao") == decisao and markov.get("confianca", 0) >= 0.60 else 0,
            1 if alt.get("alternando") and
                 ((alt.get("ultima") == "V" and decisao == "P") or
                  (alt.get("ultima") == "P" and decisao == "V")) else 0,
            1 if 0.50 <= ent <= 0.85 else 0,
        ])
        detalhes["indicadores_ok"] = indicadores_ok
        if indicadores_ok < MOTOR_MIN_INDICADORES_OK:
            return self._indeciso(
                f"apenas {indicadores_ok}/{MOTOR_MIN_INDICADORES_OK} indicadores concordam — sinal fraco"
            )

        score = int(min(100, confianca * 90 + (5 if 0.5 <= ent <= 0.85 else 0)))

        return {
            "decisao":   decisao,
            "confianca": round(confianca, 4),
            "score":     score,
            "motivos":   motivos,
            "detalhes":  detalhes,
            "pontos_v":  round(pontos_v, 1),
            "pontos_p":  round(pontos_p, 1),
            "indeciso":  False,
        }

    def _indeciso(self, motivo: str) -> dict:
        return {
            "decisao": None, "confianca": 0.0, "score": 0,
            "motivos": [f"❓ {motivo}"],
            "detalhes": {}, "pontos_v": 0.0, "pontos_p": 0.0, "indeciso": True,
        }

    def _tendencia(self, vp: list) -> dict:
        jan10 = vp[-self.JANELA_TENDENCIA:] if len(vp) >= self.JANELA_TENDENCIA else vp
        v10   = jan10.count("V")
        p10   = jan10.count("P")
        diff  = abs(v10 - p10)
        if diff >= 7:   forca = "forte"
        elif diff >= 4: forca = "moderada"
        elif diff >= 2: forca = "fraca"
        else:           forca = "equilibrada"
        dominante = None
        if diff >= 2:
            dominante = "V" if v10 > p10 else "P"
        return {"dominante": dominante, "forca": forca, "v10": v10, "p10": p10}

    def _rsi(self, vp: list, alvo: str = "V") -> float:
        janela = vp[-self.JANELA_RSI:]
        if len(janela) < 5:
            return 50.0
        vals   = [1.0 if c == alvo else 0.0 for c in janela]
        gains  = [max(vals[i] - vals[i-1], 0) for i in range(1, len(vals))]
        losses = [max(vals[i-1] - vals[i], 0) for i in range(1, len(vals))]
        ag = sum(gains)  / len(gains)  if gains  else 0
        al = sum(losses) / len(losses) if losses else 0
        if al == 0:  return 100.0
        if ag == 0:  return 0.0
        return round(100 - (100 / (1 + ag / al)), 1)

    def _cluster(self, vp: list) -> dict:
        cor = None
        tam = 0
        for c in reversed(vp):
            if c not in ("V", "P"):
                continue
            if cor is None:
                cor = c; tam = 1
            elif c == cor:
                tam += 1
            else:
                break
        return {"cor": cor, "tamanho": tam}

    def _markov(self, vp: list, order: int = 3) -> Optional[dict]:
        if len(vp) < order + 5:
            return None
        trans: dict = {}
        for i in range(len(vp) - order):
            state = tuple(vp[i:i + order])
            nxt   = vp[i + order]
            if nxt not in ("V", "P"):
                continue
            if state not in trans:
                trans[state] = {"V": 0, "P": 0}
            trans[state][nxt] += 1
        state_atual = tuple(vp[-order:])
        counts = trans.get(state_atual)
        if not counts:
            return None
        total = sum(counts.values())
        if total < 5:
            return None
        previsao  = max(counts, key=counts.get)
        confianca = counts[previsao] / total
        return {"previsao": previsao, "confianca": round(confianca, 4), "amostras": total}

    def _alternancia(self, vp: list) -> dict:
        if len(vp) < 6:
            return {"alternando": False, "ultima": None}
        jan  = vp[-6:]
        alts = sum(1 for i in range(1, len(jan)) if jan[i] != jan[i-1])
        return {"alternando": alts >= 4, "ultima": jan[-1]}

    def _entropia(self, vp: list) -> float:
        jan = vp[-20:] if len(vp) >= 20 else vp
        if len(jan) < 4:
            return 1.0
        total = len(jan)
        ent   = 0.0
        for c in ("V", "P"):
            p = jan.count(c) / total
            if p > 0:
                ent -= p * math.log2(p)
        return round(ent / math.log2(2), 4)

    def build_telegram_msg(self, resultado: dict) -> str:
        if resultado["indeciso"]:
            return f"🤔 <b>Motor VP Indeciso</b>\n{resultado['motivos'][0]}"
        decisao   = resultado["decisao"]
        confianca = resultado["confianca"]
        score     = int(resultado["score"])
        emoji_dec = COLOR_LETTER_TO_EMOJI.get(decisao, "?")
        label_dec = COLOR_LETTER_TO_LABEL.get(decisao, decisao)
        barra     = "█" * (int(score) // 10) + "░" * (10 - int(score) // 10)
        if confianca >= 0.80:   nivel, nivel_e = "ALTA",  "🟢"
        elif confianca >= 0.65: nivel, nivel_e = "MÉDIA", "🟡"
        else:                   nivel, nivel_e = "BAIXA", "🟠"
        motivos_txt = "\n".join(f"   {m}" for m in resultado["motivos"])
        return (
            f"🤖 <b>DECISÃO AUTÔNOMA VP</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Cor escolhida: {emoji_dec} <b>{label_dec}</b>\n"
            f"📊 Confiança: {nivel_e} <b>{nivel} ({confianca:.0%})</b>\n"
            f"⚡ Score: <b>{score}/100</b>  <code>[{barra}]</code>\n"
            f"📈 Pontuação: 🔴{resultado['pontos_v']} × ⚫{resultado['pontos_p']}\n\n"
            f"<b>🔍 Análise completa:</b>\n{motivos_txt}"
        )


_motor_decisao = MotorDecisaoVP()


class GestorBancaProgressiva:
    """
    Martingale puro com 2 gales máx.
    - Banca: R$ 500
    - Entrada base: R$ 1,00
    - Gale 1:       R$ 2,00  (2x)
    - Gale 2:       R$ 4,00  (4x)
    - WIN em qualquer gale → reseta para R$ 1,00
    - LOSS no gale 2       → reseta para R$ 1,00 (ciclo encerrado)
    """
    FILENAME = "banca_saldo_e_nivel.json"

    def __init__(self, banca_inicial: float = 500.0, entrada_base: float = 1.0):
        self.banca_inicial  = banca_inicial
        self.entrada_base   = entrada_base   # R$ 1,00
        self.banca_atual    = banca_inicial
        self.nivel_atual    = 1              # 1 = entrada base, 2 = G1, 3 = G2

        # Tabela martingale: entrada × 2^(gale)
        self.TABELA = {
            1: round(entrada_base,          2),   # R$ 1,00  — sinal direto
            2: round(entrada_base * 2.0,    2),   # R$ 2,00  — Gale 1
            3: round(entrada_base * 4.0,    2),   # R$ 4,00  — Gale 2
        }

        # Contadores por tipo
        self.wins_direto    = 0;  self.losses_direto   = 0
        self.wins_gale1     = 0;  self.losses_gale1    = 0
        self.wins_gale2     = 0;  self.losses_gale2    = 0
        self.wins_cor_dom   = 0;  self.losses_cor_dom  = 0

        # PnL real por tipo
        self.pnl_direto     = 0.0
        self.pnl_gale1      = 0.0
        self.pnl_gale2      = 0.0
        self.pnl_cor_dom    = 0.0

        self._load()
        log.info(
            f"💰 Banca Martingale | R${self.banca_atual:.2f} | "
            f"base=R${self.entrada_base:.2f} | "
            f"G1=R${self.TABELA[2]:.2f} | G2=R${self.TABELA[3]:.2f}"
        )

    # ── Persistência ───────────────────────────────────────────

    def _load(self):
        if os.path.exists(self.FILENAME):
            try:
                with open(self.FILENAME, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if (d.get("banca_inicial") == self.banca_inicial and
                        d.get("entrada_base") == self.entrada_base):
                    self.banca_atual    = d.get("banca_atual",    self.banca_inicial)
                    self.nivel_atual    = d.get("nivel_atual",    1)
                    self.wins_direto    = d.get("wins_direto",    0)
                    self.losses_direto  = d.get("losses_direto",  0)
                    self.wins_gale1     = d.get("wins_gale1",     0)
                    self.losses_gale1   = d.get("losses_gale1",   0)
                    self.wins_gale2     = d.get("wins_gale2",     0)
                    self.losses_gale2   = d.get("losses_gale2",   0)
                    self.wins_cor_dom   = d.get("wins_cor_dom",   0)
                    self.losses_cor_dom = d.get("losses_cor_dom", 0)
                    self.pnl_direto     = d.get("pnl_direto",    0.0)
                    self.pnl_gale1      = d.get("pnl_gale1",     0.0)
                    self.pnl_gale2      = d.get("pnl_gale2",     0.0)
                    self.pnl_cor_dom    = d.get("pnl_cor_dom",   0.0)
                    log.info(f"Banca restaurada: R${self.banca_atual:.2f} | Nível {self.nivel_atual}")
                else:
                    log.info("Config de banca alterado — reiniciando.")
                    self._save()
            except Exception as e:
                log.error(f"Erro ao carregar banca: {e}")
        else:
            self._save()

    def _save(self):
        try:
            with open(self.FILENAME, "w", encoding="utf-8") as f:
                json.dump({
                    "banca_inicial":  self.banca_inicial,
                    "entrada_base":   self.entrada_base,
                    "banca_atual":    round(self.banca_atual, 2),
                    "nivel_atual":    self.nivel_atual,
                    "tabela":         self.TABELA,
                    "wins_direto":    self.wins_direto,
                    "losses_direto":  self.losses_direto,
                    "wins_gale1":     self.wins_gale1,
                    "losses_gale1":   self.losses_gale1,
                    "wins_gale2":     self.wins_gale2,
                    "losses_gale2":   self.losses_gale2,
                    "wins_cor_dom":   self.wins_cor_dom,
                    "losses_cor_dom": self.losses_cor_dom,
                    "pnl_direto":     round(self.pnl_direto,   2),
                    "pnl_gale1":      round(self.pnl_gale1,    2),
                    "pnl_gale2":      round(self.pnl_gale2,    2),
                    "pnl_cor_dom":    round(self.pnl_cor_dom,  2),
                }, f, indent=4, ensure_ascii=False)
        except Exception as e:
            log.error(f"Erro ao salvar banca: {e}")

    # ── Consulta ───────────────────────────────────────────────

    def get_valor_aposta(self) -> float:
        """Retorna valor da aposta atual baseado no nível martingale."""
        return self.TABELA.get(self.nivel_atual, self.entrada_base)

    def gale1_permitido(self) -> bool:
        """Sempre permite gale — é martingale puro."""
        return True

    # ── Registro de resultados ────────────────────────────────

    def _delta_banca(self, valor_apostado: float, win: bool) -> float:
        """
        No martingale da Blaze Double (payout 2x para P/V):
          WIN  → lucro líquido = valor_apostado × 1  (recebe 2x, descontando entrada)
          LOSS → prejuízo      = valor_apostado × 1  (perde o que apostou)
        """
        return round(valor_apostado, 2)

    def registrar_win(self, payout: float, gale_attempt: int = 0) -> None:
        """
        WIN em qualquer gale:
          - Acumula o lucro líquido real no PnL
          - Reseta nível para 1 (próxima entrada começa em R$1)
        """
        valor_apostado = self.get_valor_aposta()
        lucro          = round(valor_apostado * (payout - 1), 2)  # lucro líquido

        if gale_attempt == 0:
            self.wins_direto += 1
            self.pnl_direto  += lucro
        elif gale_attempt == 1:
            self.wins_gale1  += 1
            self.pnl_gale1   += lucro
        else:
            self.wins_gale2  += 1
            self.pnl_gale2   += lucro

        self.banca_atual += lucro
        self.nivel_atual  = 1   # reseta martingale
        log.info(
            f"WIN gale={gale_attempt} | apostei R${valor_apostado:.2f} | "
            f"+R${lucro:.2f} | banca R${self.banca_atual:.2f} | "
            f"próxima R${self.TABELA[1]:.2f}"
        )
        self._save()

    def registrar_loss(self, gale_attempt: int = 0) -> None:
        """
        LOSS:
          - Deduz o valor apostado da banca
          - Se ainda tem gale disponível → avança nível (dobra)
          - Se perdeu o gale 2 (gale_attempt=2) → reseta para nível 1
        """
        valor_apostado = self.get_valor_aposta()
        prejuizo       = valor_apostado  # perde o que apostou

        if gale_attempt == 0:
            self.losses_direto += 1
            self.pnl_direto    -= prejuizo
        elif gale_attempt == 1:
            self.losses_gale1  += 1
            self.pnl_gale1     -= prejuizo
        else:
            self.losses_gale2  += 1
            self.pnl_gale2     -= prejuizo

        self.banca_atual -= prejuizo

        # Martingale: avança nível se ainda tem gale
        if self.nivel_atual < 3:
            self.nivel_atual += 1
            proximo = self.TABELA.get(self.nivel_atual, self.entrada_base)
            log.info(
                f"LOSS gale={gale_attempt} | -R${prejuizo:.2f} | "
                f"banca R${self.banca_atual:.2f} | "
                f"⬆️ martingale → R${proximo:.2f}"
            )
        else:
            # Perdeu G2 — reseta ciclo
            self.nivel_atual = 1
            log.info(
                f"LOSS gale={gale_attempt} (G2) | -R${prejuizo:.2f} | "
                f"banca R${self.banca_atual:.2f} | "
                f"🔄 ciclo encerrado → próxima R${self.TABELA[1]:.2f}"
            )
        self._save()

    def registrar_cor_dominante(self, win: bool) -> None:
        """Cor dominante usa sempre entrada_base (sem martingale)."""
        valor = self.entrada_base
        if win:
            lucro = round(valor * 1.0, 2)
            self.wins_cor_dom  += 1
            self.pnl_cor_dom   += lucro
            self.banca_atual   += lucro
            log.info(f"COR-DOM WIN | +R${lucro:.2f} | banca R${self.banca_atual:.2f}")
        else:
            self.losses_cor_dom += 1
            self.pnl_cor_dom    -= valor
            self.banca_atual    -= valor
            log.info(f"COR-DOM LOSS | -R${valor:.2f} | banca R${self.banca_atual:.2f}")
        self._save()

    def resumo_tipos(self) -> str:
        """Bloco de texto para Telegram com stats por tipo."""
        def wr(w, l):
            t = w + l
            return f"{w/t*100:.0f}%" if t > 0 else "—"
        def sinal(v):
            return ("+" if v >= 0 else "") + f"R${v:.2f}"

        pnl_total = self.pnl_direto + self.pnl_gale1 + self.pnl_gale2 + self.pnl_cor_dom
        return (
            f"🎯 <b>Win Direto</b>:  "
            f"✅{self.wins_direto} ❌{self.losses_direto}  {wr(self.wins_direto,self.losses_direto)}  "
            f"{sinal(self.pnl_direto)}\n"
            f"1️⃣ <b>Gale 1</b> (R${self.TABELA[2]:.2f}):  "
            f"✅{self.wins_gale1} ❌{self.losses_gale1}  {wr(self.wins_gale1,self.losses_gale1)}  "
            f"{sinal(self.pnl_gale1)}\n"
            f"2️⃣ <b>Gale 2</b> (R${self.TABELA[3]:.2f}):  "
            f"✅{self.wins_gale2} ❌{self.losses_gale2}  {wr(self.wins_gale2,self.losses_gale2)}  "
            f"{sinal(self.pnl_gale2)}\n"
            f"🎨 <b>Cor Dom</b>:  "
            f"✅{self.wins_cor_dom} ❌{self.losses_cor_dom}  {wr(self.wins_cor_dom,self.losses_cor_dom)}  "
            f"{sinal(self.pnl_cor_dom)}\n"
            f"{'─'*20}\n"
            f"💰 <b>P&L Total: {sinal(pnl_total)}</b>"
        )


class RSIAdaptado:
    PERIOD    = 14
    OVERBOUGHT = 70
    OVERSOLD   = 30

    def _encode(self, color: str) -> float:
        return {"V": 1.0, "P": 0.5}.get(color, 0.5)

    def calculate(self, history: list, color: str) -> dict:
        window = [c for c in history[-self.PERIOD:] if c in ("V", "P")]
        if len(window) < 5:
            return {"rsi": 50.0, "zona": "sem dados", "alerta": False,
                    "linha": "📈 RSI: <i>dados insuficientes</i>"}
        vals   = [self._encode(c) for c in window]
        gains  = [max(vals[i] - vals[i-1], 0) for i in range(1, len(vals))]
        losses = [max(vals[i-1] - vals[i], 0) for i in range(1, len(vals))]
        ag = sum(gains) / len(gains) if gains else 0
        al = sum(losses) / len(losses) if losses else 0
        if al == 0:  rsi = 100.0
        elif ag == 0: rsi = 0.0
        else:         rsi = 100 - (100 / (1 + ag / al))
        if rsi >= self.OVERBOUGHT:
            zona, emoji, alerta = "sobrecomprado", "🔴", True
        elif rsi <= self.OVERSOLD:
            zona, emoji, alerta = "sobrevendido",  "🟢", False
        else:
            zona, emoji, alerta = "neutro",        "🟡", False
        barra = "█" * int(rsi / 10) + "░" * (10 - int(rsi / 10))
        cor_l = "🔴" if color == "V" else "⚫"
        linha = f"📈 <b>RSI</b> {emoji} <b>{rsi:.0f}</b>  <code>[{barra}]</code>  <i>{zona} {cor_l}</i>"
        if alerta:
            linha += "  ⚠️ reversão provável"
        return {"rsi": rsi, "zona": zona, "alerta": alerta, "linha": linha}


class FiltroHorario:
    MIN_AMOSTRAS = 3
    BOM  = 65
    RUIM = 45

    def avaliar(self, pattern_records: dict, ks: str) -> dict:
        hora    = datetime.now().strftime("%H")
        rec     = pattern_records.get(ks)
        if not rec or not rec.hour_total:
            return {"status": "sem_dados", "winrate_hora": 0.0,
                    "linha": "🕐 Horário: <i>sem histórico</i>", "score_bonus": 0}
        total_h = rec.hour_total.get(hora, 0)
        wins_h  = rec.hour_wins.get(hora, 0)
        if total_h < self.MIN_AMOSTRAS:
            h    = int(hora)
            adjs = [f"{(h-1)%24:02d}", f"{(h+1)%24:02d}"]
            t2   = sum(rec.hour_total.get(a, 0) for a in adjs)
            w2   = sum(rec.hour_wins.get(a, 0)  for a in adjs)
            if t2 >= self.MIN_AMOSTRAS:
                return self._cls(w2/t2*100, hora, t2, adj=True)
            return {"status": "sem_dados", "winrate_hora": 0.0,
                    "linha": f"🕐 {hora}h: <i>poucas amostras ({total_h})</i>", "score_bonus": 0}
        return self._cls(wins_h / total_h * 100, hora, total_h)

    def _cls(self, wr, hora, n, adj=False):
        s = " (±1h)" if adj else ""
        if wr >= self.BOM:
            return {"status": "bom",    "winrate_hora": wr, "score_bonus": 15,
                    "linha": f"🕐 {hora}h{s}: ✅ <b>{wr:.0f}%</b> ({n} entradas) — favorável"}
        elif wr >= 50:
            return {"status": "neutro", "winrate_hora": wr, "score_bonus": 5,
                    "linha": f"🕐 {hora}h{s}: 🟡 <b>{wr:.0f}%</b> ({n} entradas)"}
        return {"status": "ruim",   "winrate_hora": wr, "score_bonus": -10,
                "linha": f"🕐 {hora}h{s}: ⚠️ <b>{wr:.0f}%</b> ({n} entradas) — fraco"}


class ScoreConfianca:
    def calcular(self, winrate: float, n_conf: int, markov: float,
                 rsi_alerta: bool, bonus_hora: int, streak: int,
                 entropia: float, total_ent: int,
                 bonus_regime: int = 0) -> dict:
        s = 0
        s += min(25, (winrate/100)*25) if total_ent >= 5 else 12
        s += {1:5, 2:14, 3:18, 4:20}.get(min(n_conf, 4), 20)
        s += min(20, markov * 20)
        s += 3 if rsi_alerta else 15
        s += max(-10, min(10, bonus_hora))
        s += min(5, streak * 1.5)
        s += 5 if 0.60 <= entropia <= 0.85 else (2 if 0.50 <= entropia <= 0.95 else 0)
        # ── Bônus/penalidade do regime ──────────────────────────────
        s += bonus_regime
        s = max(0, min(100, s))
        if s >= 80:   cl, em, cv = "FORTE", "🟢", "Alta confiança"
        elif s >= 60: cl, em, cv = "MÉDIO", "🟡", "Entrada normal"
        elif s >= 40: cl, em, cv = "FRACO", "🟠", "Cuidado — gale menor"
        else:         cl, em, cv = "BAIXO", "🔴", "Máxima atenção"
        barra = "█" * int(s/10) + "░" * (10 - int(s/10))
        linha = (f"⚡ <b>Score: {s:.0f}/100</b>  {em}  <code>[{barra}]</code>\n"
                 f"   <b>{cl}</b> — <i>{cv}</i>")
        return {"score": s, "classe": cl, "emoji": em, "conselho": cv, "linha": linha}


class PesoDinamicoLista:
    def avaliar(self, ab) -> dict:
        listas = {n: {"acc": getattr(ab, f"acc_{n.lower()}"),
                      "total": getattr(ab, f"total_{n.lower()}")}
                  for n in ("A","B","C","D")
                  if getattr(ab, f"total_{n.lower()}") >= 3}
        if not listas:
            return {"melhor": None, "linha": "📂 Listas: <i>coletando dados...</i>"}
        melhor = max(listas, key=lambda k: listas[k]["acc"])
        partes = [f"{'⭐' if n==melhor else '  '}{n}:{d['acc']:.0f}%"
                  for n, d in sorted(listas.items())]
        return {"melhor": melhor, "acc": listas[melhor]["acc"],
                "linha": f"📂 {'|'.join(partes)} → 🏆 <b>Lista {melhor} ({listas[melhor]['acc']:.0f}%)</b>"}


_rsi_ind     = RSIAdaptado()
_filtro_hora = FiltroHorario()
_score_ind   = ScoreConfianca()
_peso_lista  = PesoDinamicoLista()


@dataclass
class Config:
    url: str
    token: str
    chat_id: int
    sticker_win: str
    sticker_loss: str
    sticker_pybots: str
    max_gale: int = 2
    max_loss_streak: int = 3
    banca_inicial: float = 500.0
    entrada_base: float = 1.0
    proxy: Optional[str] = None
    tg_api_id:   int = 0
    tg_api_hash: str = ""
    tg_phone:    str = ""
    blaze_email:    str = ""
    blaze_password: str = ""
    autobet: "AutoBetConfig" = field(default_factory=AutoBetConfig)

    @classmethod
    def from_file(cls, path: str = "config.ini") -> "Config":
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf-8")

        proxy_ini = cfg.get("bot_config", "proxy", fallback="").strip() or None
        proxy_env = (os.environ.get("HTTPS_PROXY") or
                     os.environ.get("HTTP_PROXY") or
                     os.environ.get("ALL_PROXY"))
        proxy = proxy_ini or proxy_env or None

        return cls(
            url=cfg.get("url_cassino", "url"),
            token=cfg.get("bot_config", "api_key"),
            chat_id=int(cfg.get("bot_config", "chat_id")),
            sticker_win=cfg.get("bot_config", "sticker_win"),
            sticker_loss=cfg.get("bot_config", "sticker_loss"),
            sticker_pybots=cfg.get("bot_config", "sticker_pybots"),
            max_gale=cfg.getint("bot_config", "max_gale",              fallback=2),
            max_loss_streak=cfg.getint("bot_config", "max_loss_streak", fallback=3),
            banca_inicial=cfg.getfloat("bot_config", "banca_inicial",  fallback=500.0),
            entrada_base=cfg.getfloat("bot_config",  "entrada_base",   fallback=1.0),
            proxy=proxy,
            tg_api_id=cfg.getint("telegram",   "api_id",   fallback=0),
            tg_api_hash=cfg.get("telegram",    "api_hash", fallback=""),
            tg_phone=cfg.get("telegram",       "phone",    fallback=""),
            blaze_email=cfg.get("blaze_auth",    "email",    fallback=""),
            blaze_password=cfg.get("blaze_auth", "password", fallback=""),
            autobet=AutoBetConfig.from_ini(cfg),
        )


@dataclass
class ABCTracker:
    wins_a: int = 0; losses_a: int = 0
    wins_b: int = 0; losses_b: int = 0
    wins_c: int = 0; losses_c: int = 0
    wins_d: int = 0; losses_d: int = 0
    last_report_total: int = 0

    @property
    def total_a(self) -> int: return self.wins_a + self.losses_a
    @property
    def total_b(self) -> int: return self.wins_b + self.losses_b
    @property
    def total_c(self) -> int: return self.wins_c + self.losses_c
    @property
    def total_d(self) -> int: return self.wins_d + self.losses_d
    @property
    def acc_a(self) -> float: return (self.wins_a/self.total_a*100) if self.total_a>0 else 0.0
    @property
    def acc_b(self) -> float: return (self.wins_b/self.total_b*100) if self.total_b>0 else 0.0
    @property
    def acc_c(self) -> float: return (self.wins_c/self.total_c*100) if self.total_c>0 else 0.0
    @property
    def acc_d(self) -> float: return (self.wins_d/self.total_d*100) if self.total_d>0 else 0.0

    def register(self, lista: str, win: bool) -> None:
        attr = f"wins_{lista.lower()}" if win else f"losses_{lista.lower()}"
        if hasattr(self, attr):
            setattr(self, attr, getattr(self, attr) + 1)

    def best_list(self) -> str:
        scores = {k: getattr(self, f"acc_{k.lower()}")
                  for k in ("A","B","C","D")
                  if getattr(self, f"total_{k.lower()}") >= 5}
        return max(scores, key=scores.get) if scores else ""

    def should_report(self) -> bool:
        total_now = max(self.total_a, self.total_b, self.total_c, self.total_d)
        return (total_now - self.last_report_total) >= AB_REPORT_INTERVAL

    def build_report(self) -> str:
        melhor = self.best_list()
        winner = f"🏆 <b>Lista {melhor} está ganhando!</b>" if melhor else "⏳ Coletando dados..."
        return (
            f"📊 <b>Comparativo A/B/C/D — {AB_REPORT_INTERVAL} sinais</b>\n"
            f"🎯 Modo: <b>🔴 Vermelho + ⚫ Preto (Padrões 5-6 | 90%)</b>\n\n"
            f"🅰️ <b>Lista A</b> — padroes_lista_A_normal.json\n"
            f"✅ {self.wins_a}W  ❌ {self.losses_a}L  📈 {self.acc_a:.1f}%\n\n"
            f"🅱️ <b>Lista B</b> — padroes_lista_B_top.json\n"
            f"✅ {self.wins_b}W  ❌ {self.losses_b}L  📈 {self.acc_b:.1f}%\n\n"
            f"🏅 <b>Lista C</b> — padroes_lista_C_elite.json\n"
            f"✅ {self.wins_c}W  ❌ {self.losses_c}L  📈 {self.acc_c:.1f}%\n\n"
            f"📂 <b>Lista D</b> — padroes_lista_D_origem.json\n"
            f"✅ {self.wins_d}W  ❌ {self.losses_d}L  📈 {self.acc_d:.1f}%\n\n"
            f"{winner}"
        )

    def mark_reported(self) -> None:
        self.last_report_total = max(self.total_a, self.total_b, self.total_c, self.total_d)


@dataclass
class Stats:
    total_signals: int = 0
    wins: int = 0
    losses: int = 0
    win_normal: int = 0
    win_gale: int = 0
    consecutive_wins: int = 0
    max_consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0   # ← maior sequência de losses da sessão
    last_results: list = field(default_factory=list)

    # ── CONTADORES DIÁRIOS ────────────────────────────────────────
    wins_hoje: int = 0
    losses_hoje: int = 0
    total_hoje: int = 0
    data_hoje: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    # Histórico de sequências de loss do dia: [(tamanho, "HH:MM"), ...]
    sequencias_loss_hoje: list = field(default_factory=list)
    _seq_loss_temp: int = 0          # contador de loss em andamento
    _seq_loss_inicio: str = ""       # hora que começou a sequência atual
    max_seq_loss_hoje: int = 0       # maior sequência de loss do dia

    def _checar_reset_dia(self) -> None:
        hoje = datetime.now().strftime("%Y-%m-%d")
        if hoje != self.data_hoje:
            self.wins_hoje = 0
            self.losses_hoje = 0
            self.total_hoje = 0
            self.data_hoje = hoje
            self.sequencias_loss_hoje = []
            self._seq_loss_temp = 0
            self._seq_loss_inicio = ""
            self.max_seq_loss_hoje = 0

    @property
    def accuracy(self) -> float:
        return (self.wins/self.total_signals*100) if self.total_signals > 0 else 0.0

    @property
    def accuracy_hoje(self) -> float:
        return (self.wins_hoje/self.total_hoje*100) if self.total_hoje > 0 else 0.0

    def register_win(self, gale_attempt: int) -> None:
        self._checar_reset_dia()
        self.wins += 1
        self.wins_hoje += 1
        self.total_hoje += 1
        self.consecutive_wins += 1
        self.consecutive_losses = 0
        if gale_attempt > 0: self.win_gale += 1
        else:                self.win_normal += 1
        if self.consecutive_wins > self.max_consecutive_wins:
            self.max_consecutive_wins = self.consecutive_wins
        # Fecha sequência de loss em andamento se havia
        if self._seq_loss_temp > 0:
            self.sequencias_loss_hoje.append(
                (self._seq_loss_temp, self._seq_loss_inicio)
            )
            if self._seq_loss_temp > self.max_seq_loss_hoje:
                self.max_seq_loss_hoje = self._seq_loss_temp
            self._seq_loss_temp = 0
            self._seq_loss_inicio = ""
        self.last_results.append("✅")
        if len(self.last_results) > 30:
            self.last_results = self.last_results[-30:]

    def register_loss(self) -> None:
        self._checar_reset_dia()
        self.losses += 1
        self.losses_hoje += 1
        self.total_hoje += 1
        self.consecutive_wins = 0
        self.consecutive_losses += 1
        if self.consecutive_losses > self.max_consecutive_losses:
            self.max_consecutive_losses = self.consecutive_losses
        # Rastreia sequência de loss do dia
        if self._seq_loss_temp == 0:
            self._seq_loss_inicio = datetime.now().strftime("%H:%M")
        self._seq_loss_temp += 1
        if self._seq_loss_temp > self.max_seq_loss_hoje:
            self.max_seq_loss_hoje = self._seq_loss_temp
        self.last_results.append("❌")
        if len(self.last_results) > 30:
            self.last_results = self.last_results[-30:]

    def losses_na_janela(self) -> int:
        return self.last_results[-JANELA_SINAIS:].count("❌")

    def janela_bloqueada(self) -> bool:
        return self.losses_na_janela() >= MAX_LOSSES_NA_JANELA

    def resumo_diario(self) -> str:
        """Retorna bloco HTML com placar do dia, sequências de loss e alertas."""
        self._checar_reset_dia()
        hoje_str = datetime.now().strftime("%d/%m")
        acc_str  = f"{self.accuracy_hoje:.1f}%" if self.total_hoje > 0 else "—"

        # Streak atual
        if self.consecutive_wins > 0:
            streak_txt = f"🔥 <b>{self.consecutive_wins} wins seguidos</b>"
        elif self.consecutive_losses > 0:
            streak_txt = f"⚠️ <b>{self.consecutive_losses} losses seguidos</b>"
        else:
            streak_txt = "—"

        # Alerta de loss consecutivo em andamento
        alerta = ""
        if self._seq_loss_temp >= 2:
            alerta = (
                f"\n🚨 <b>ATENÇÃO: {self._seq_loss_temp} losses consecutivos agora!</b> "
                f"(desde {self._seq_loss_inicio})"
            )
        elif self._seq_loss_temp == 1:
            alerta = f"\n⚠️ Loss em andamento (1 seguido)"

        # Histórico de sequências do dia
        seqs_txt = ""
        # Inclui sequência em andamento se houver
        todas = list(self.sequencias_loss_hoje)
        if self._seq_loss_temp > 0:
            todas.append((self._seq_loss_temp, self._seq_loss_inicio + "…"))
        if todas:
            partes = [f"{t}L às {h}" for t, h in todas[-5:]]  # últimas 5
            seqs_txt = f"\n💀 Seq. loss do dia: {' | '.join(partes)}"

        max_txt = f" | Maior: <b>{self.max_seq_loss_hoje}L</b>" if self.max_seq_loss_hoje >= 2 else ""

        return (
            f"📅 <b>HOJE ({hoje_str}):</b>  "
            f"✅ <b>{self.wins_hoje}W</b>  ❌ <b>{self.losses_hoje}L</b>  "
            f"📊 <b>{acc_str}</b>  🎯 {self.total_hoje} sinais"
            f"{max_txt}"
            f"{seqs_txt}"
            f"{alerta}"
        )

    def to_message(self) -> str:
        losses_j = self.losses_na_janela()
        j_emoji  = "🔴 BLOQUEADO" if losses_j >= MAX_LOSSES_NA_JANELA else f"✅ {losses_j}/{MAX_LOSSES_NA_JANELA}"
        # Streak atual
        if self.consecutive_wins > 0:
            streak_txt = f"🔥 <b>{self.consecutive_wins} wins seguidos</b>"
        elif self.consecutive_losses > 0:
            streak_txt = f"⚠️ <b>{self.consecutive_losses} losses seguidos</b>"
        else:
            streak_txt = "—"
        return (
            f"<b>🔴⚫ Placar VP: ✅ {self.wins} X {self.losses} ❌</b>\n\n"
            f"🥇 Sem Gale: <b>{self.win_normal}</b>\n"
            f"🎯 Total de sinais: <b>{self.total_signals}</b>\n"
            f"📊 Assertividade: <b>{self.accuracy:.1f}%</b>\n"
            f"🔥 Maior sequência wins: <b>{self.max_consecutive_wins}</b> "
            f"| 💀 Maior sequência losses: <b>{self.max_consecutive_losses}</b>\n"
            f"⚡ Agora: {streak_txt}\n"
            f"🚦 Janela {JANELA_SINAIS} sinais: <b>{j_emoji}</b>\n\n"
            f"{self.resumo_diario()}"
        )


@dataclass
class CandidatePattern:
    pattern: list
    prediction: str
    wins: int = 0
    losses: int = 0
    consecutive_losses: int = 0
    max_loss_streak: int = 0
    first_seen: str = ""
    last_seen: str = ""

    @property
    def total(self) -> int:    return self.wins + self.losses
    @property
    def accuracy(self) -> float: return (self.wins/self.total*100) if self.total > 0 else 0.0

    def register_win(self) -> None:
        self.wins += 1
        self.consecutive_losses = 0
        self.last_seen = datetime.now().strftime("%H:%M:%S")

    def register_loss(self) -> None:
        self.losses += 1
        self.consecutive_losses += 1
        if self.consecutive_losses > self.max_loss_streak:
            self.max_loss_streak = self.consecutive_losses
        self.last_seen = datetime.now().strftime("%H:%M:%S")

    def should_activate(self, min_rounds: int = 11, min_accuracy: float = 100.0,
                        max_gale: int = 2) -> bool:
        if self.total < min_rounds:
            return False
        if self.accuracy < min_accuracy:
            return False
        if self.total >= 5 and self.max_loss_streak > max_gale:
            return False
        return True

    def should_remove(self) -> bool:
        return self.consecutive_losses >= AUTO_LEARN_MAX_CONS_LOSS

    def to_dict(self) -> dict:
        return {"pattern": self.pattern, "prediction": self.prediction,
                "wins": self.wins, "losses": self.losses,
                "consecutive_losses": self.consecutive_losses,
                "max_loss_streak": self.max_loss_streak,
                "first_seen": self.first_seen, "last_seen": self.last_seen}

    @classmethod
    def from_dict(cls, d: dict) -> "CandidatePattern":
        return cls(pattern=d["pattern"], prediction=d["prediction"],
                   wins=d.get("wins",0), losses=d.get("losses",0),
                   consecutive_losses=d.get("consecutive_losses",0),
                   max_loss_streak=d.get("max_loss_streak",0),
                   first_seen=d.get("first_seen",""), last_seen=d.get("last_seen",""))


class AutoLearner:
    def __init__(self, sequencias_path: str, db_file: str,
                 min_rounds: int = 11, min_accuracy: float = 100.0,
                 max_gale: int = 2, label: str = "A"):
        self.sequencias_path = sequencias_path
        self.db_file         = db_file
        self.min_rounds      = min_rounds
        self.min_accuracy    = min_accuracy
        self.max_gale        = max_gale
        self.label           = label
        self.candidates: dict[str, CandidatePattern] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.db_file):
            return
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                self.candidates[k] = CandidatePattern.from_dict(v)
            log.info(f"AutoLearner [{self.label}]: {len(self.candidates)} candidatos carregados")
        except Exception as e:
            log.error(f"AutoLearner [{self.label}] load error: {e}")

    def _save(self) -> None:
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump({k: v.to_dict() for k, v in self.candidates.items()},
                          f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"AutoLearner [{self.label}] save error: {e}")

    @staticmethod
    def _cand_key(pattern: list, prediction: str) -> str:
        return json.dumps([pattern, prediction], ensure_ascii=False)

    def _load_sequencias(self) -> list:
        try:
            with open(self.sequencias_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_sequencias(self, patterns: list) -> None:
        patterns.sort(key=lambda x: len(x[0]), reverse=True)
        with open(self.sequencias_path, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2, ensure_ascii=False)

    def _is_in_sequencias(self, pattern: list, prediction: str) -> bool:
        seqs = self._load_sequencias()
        return any(s[0] == pattern and s[1] == prediction for s in seqs)

    def _tendencia_dominante(self, history: list, janela: int = 10) -> str:
        recentes = [c for c in history[-janela:] if c in ("V", "P")]
        if not recentes:
            return ""
        v = recentes.count("V")
        p = recentes.count("P")
        if abs(v - p) < 2:
            r5 = [c for c in history[-5:] if c in ("V", "P")]
            if not r5:
                return ""
            v5 = r5.count("V"); p5 = r5.count("P")
            if abs(v5 - p5) >= 2:
                return "V" if v5 > p5 else "P"
            return ""
        return "V" if v > p else "P"

    def discover(self, history: list, global_seen: set = None) -> list:
        history_vp = [c for c in history if c in ("V", "P")]
        min_len    = max(AUTO_LEARN_PAT_SIZES) + 1
        if len(history_vp) < min_len:
            return []

        ultima_cor = history_vp[-1]
        tendencia  = self._tendencia_dominante(history_vp)
        if not tendencia or ultima_cor not in ("V", "P"):
            return []

        v_count = history_vp[-10:].count("V")
        p_count = history_vp[-10:].count("P")
        new_candidates = []

        for size in AUTO_LEARN_PAT_SIZES:
            if len(history_vp) < size + 1:
                continue
            segment    = history_vp[-(size + 1):]
            pattern    = segment[:-1]
            prediction = segment[-1]

            if prediction not in ("V", "P"):
                continue
            if prediction != tendencia:
                continue
            if not all(c in ("V", "P") for c in pattern):
                continue
            if self._is_in_sequencias(pattern, prediction):
                continue

            key = self._cand_key(pattern, prediction)
            if key not in self.candidates:
                cand = CandidatePattern(
                    pattern=pattern, prediction=prediction,
                    first_seen=datetime.now().strftime("%H:%M:%S"),
                )
                self.candidates[key] = cand
                new_candidates.append(cand)
                if global_seen is not None:
                    if key not in global_seen:
                        global_seen.add(key)
                        log.info(
                            f"AutoLearner VP [{self.label}]: novo candidato "
                            f"(tam {size}) {pattern}→{prediction} "
                            f"[tend={tendencia} 🔴{v_count}×⚫{p_count}×]"
                        )
                else:
                    log.info(
                        f"AutoLearner VP [{self.label}]: novo candidato "
                        f"(tam {size}) {pattern}→{prediction}"
                    )
        return new_candidates

    def update(self, history: list) -> tuple[list, list]:
        history_vp = [c for c in history if c in ("V", "P")]
        promoted   = []
        removed    = []
        if len(history_vp) < 2:
            return promoted, removed
        last_color = history_vp[-1]

        for key, cand in list(self.candidates.items()):
            size = len(cand.pattern)
            if len(history_vp) < size + 1:
                continue
            segment = history_vp[-(size + 1):-1]
            if segment != cand.pattern:
                continue
            if last_color == cand.prediction:
                cand.register_win()
            else:
                cand.register_loss()

            if cand.should_activate(self.min_rounds, self.min_accuracy, self.max_gale):
                seqs = self._load_sequencias()
                if not self._is_in_sequencias(cand.pattern, cand.prediction):
                    seqs.append([cand.pattern, cand.prediction])
                    self._save_sequencias(seqs)
                    promoted.append(cand)
                    log.info(
                        f"AutoLearner VP [{self.label}]: PROMOVIDO "
                        f"{cand.pattern}→{cand.prediction} "
                        f"({cand.accuracy:.1f}% em {cand.total} testes)"
                    )
                del self.candidates[key]
            elif cand.should_remove():
                removed.append(cand)
                del self.candidates[key]

        self._save()
        return promoted, removed

    def cleanup_hopeless(self) -> int:
        removidos = 0
        for key, cand in list(self.candidates.items()):
            if cand.total == 0:
                continue
            rodadas_faltam = max(0, self.min_rounds - cand.total)
            max_wins  = cand.wins + rodadas_faltam
            max_total = cand.total + rodadas_faltam
            max_acc   = (max_wins / max_total * 100) if max_total > 0 else 0
            if max_acc < self.min_accuracy:
                del self.candidates[key]
                removidos += 1
        if removidos > 0:
            self._save()
        return removidos

    def remove_active_pattern(self, pattern: list, prediction: str) -> bool:
        seqs   = self._load_sequencias()
        before = len(seqs)
        seqs   = [s for s in seqs if not (s[0] == pattern and s[1] == prediction)]
        if len(seqs) < before:
            self._save_sequencias(seqs)
            return True
        return False

    def stats_summary(self) -> str:
        total = len(self.candidates)
        if total == 0:
            return f"🤖 <b>AutoLearner VP [{self.label}]</b>: nenhum candidato em teste."
        ready = sum(1 for c in self.candidates.values() if c.total >= self.min_rounds)
        return (
            f"🤖 <b>AutoLearner VP [{self.label}]</b>\n"
            f"🔬 Candidatos: <b>{total}</b> | Prontos para avaliar: <b>{ready}</b>\n"
            f"📏 Tamanhos: <b>5 e 6</b> | Critério: <b>{self.min_rounds} testes / {self.min_accuracy:.0f}%</b>"
        )


class PatternNameRegistry:
    def __init__(self):
        self._map: dict        = {}
        self._names_used: set  = set()
        self._counter: int     = 0

    @staticmethod
    def _key_str(key: tuple) -> str:
        pattern, pred = key
        return json.dumps([list(pattern), pred], ensure_ascii=False)

    def get_name(self, key: tuple) -> str:
        ks = self._key_str(key)
        if ks not in self._map:
            pattern, pred = key
            tentativa = 0
            while True:
                candidato = _candidato_nome(list(pattern), pred, tentativa)
                if candidato not in self._names_used:
                    self._map[ks]   = candidato
                    self._names_used.add(candidato)
                    self._counter  += 1
                    break
                tentativa += 1
        return self._map[ks]

    def to_dict(self) -> dict:
        return {"map": self._map, "counter": self._counter}

    def from_dict(self, data: dict) -> None:
        self._map     = data.get("map", {})
        self._counter = data.get("counter", 0)
        self._names_used = set(self._map.values())
        for ks, nome_antigo in list(self._map.items()):
            if len(nome_antigo) != 9:
                try:
                    parsed        = json.loads(ks)
                    pattern, pred = parsed[0], parsed[1]
                    self._names_used.discard(nome_antigo)
                    tentativa = 0
                    while True:
                        candidato = _candidato_nome(list(pattern), pred, tentativa)
                        if candidato not in self._names_used:
                            self._map[ks] = candidato
                            self._names_used.add(candidato)
                            break
                        tentativa += 1
                except Exception:
                    pass


@dataclass
class PatternRecord:
    wins: int = 0
    losses: int = 0
    current_win_streak: int = 0
    current_loss_streak: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    best_accuracy: float = 0.0
    last_result: str = ""
    today_count: int = 0
    total_count: int = 0
    last_used: str = ""
    last_used_date: str = ""
    wins_in_gale: int = 0
    last_seen_round: int = 0
    gap_sum: int = 0
    gap_count: int = 0
    max_gap: int = 0
    hour_wins: dict = field(default_factory=dict)
    hour_total: dict = field(default_factory=dict)
    last_results: list = field(default_factory=list)
    entries_since_last_loss: int = 0
    last_loss_entry: int = 0
    wins_after_streak: dict = field(default_factory=dict)
    current_round_ref: int = 0
    score_minimo_individual: int = SCORE_MIN_INICIAL
    # ── Exclusão dinâmica por losses consecutivos ────────────────
    losses_consecutivos_exclusao: int = 0  # losses consecutivos; 2 = exclui
    wins_acumulados_exclusao:     int = 0  # wins acumulados; zera a cada 10 (estatística)

    def register_win(self, gale_attempt: int = 0) -> None:
        self.wins += 1
        self.current_win_streak += 1
        self.current_loss_streak = 0
        self.entries_since_last_loss += 1
        if self.current_win_streak > self.max_win_streak:
            self.max_win_streak = self.current_win_streak
        if self.accuracy > self.best_accuracy:
            self.best_accuracy = round(self.accuracy, 1)
        if gale_attempt > 0:
            self.wins_in_gale += 1
        self.last_result = "✅ WIN"
        # WIN: score minimo desce -1 (padrao provado, fica mais facil entrar)
        self.score_minimo_individual = max(self.score_minimo_individual - SCORE_MIN_PASSO, SCORE_MIN_FLOOR)
        _hora = datetime.now().strftime("%H:%M")
        self.last_results.append(("✅", _hora))
        # ── EXPANDIDO PARA 30 ──────────────────────────────────────
        if len(self.last_results) > 30:
            self.last_results = self.last_results[-30:]
        self._update_usage()

    def register_loss(self) -> None:
        streak_key = str(self.current_win_streak)
        if streak_key not in self.wins_after_streak:
            self.wins_after_streak[streak_key] = [0, 0]
        self.wins_after_streak[streak_key][1] += 1
        self.losses += 1
        self.current_loss_streak += 1
        self.current_win_streak   = 0
        self.entries_since_last_loss = 0
        self.last_loss_entry      = self.total
        if self.current_loss_streak > self.max_loss_streak:
            self.max_loss_streak = self.current_loss_streak
        self.last_result = "❌ LOSS"
        # LOSS: score minimo sobe +1 (padrao falhou, exige mais na proxima)
        self.score_minimo_individual = min(self.score_minimo_individual + SCORE_MIN_PASSO, SCORE_MIN_TETO)
        _hora = datetime.now().strftime("%H:%M")
        self.last_results.append(("❌", _hora))
        # ── EXPANDIDO PARA 30 ──────────────────────────────────────
        if len(self.last_results) > 30:
            self.last_results = self.last_results[-30:]
        self._update_usage()

    def register_appearance(self, current_round: int) -> None:
        self.current_round_ref = current_round
        if self.last_seen_round > 0:
            gap = current_round - self.last_seen_round
            self.gap_sum   += gap
            self.gap_count += 1
            if gap > self.max_gap:
                self.max_gap = gap
        self.last_seen_round = current_round

    def _update_usage(self) -> None:
        now       = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        hour_str  = now.strftime("%H")
        self.last_used = now.strftime("%H:%M:%S")
        if self.last_used_date != today_str:
            self.today_count    = 0
            self.last_used_date = today_str
        self.today_count += 1
        self.total_count += 1
        self.hour_total[hour_str] = self.hour_total.get(hour_str, 0) + 1
        if self.last_result == "✅ WIN":
            self.hour_wins[hour_str] = self.hour_wins.get(hour_str, 0) + 1

    @property
    def total(self) -> int:    return self.wins + self.losses
    @property
    def accuracy(self) -> float: return (self.wins/self.total*100) if self.total > 0 else 0.0

    @property
    def visual_history(self) -> str:
        """
        Exibe os últimos 30 resultados em blocos de 10 por linha,
        cada item no formato: ✅10:50 ou ❌16:02
        """
        if not self.last_results:
            return "⬜ Sem histórico ainda"
        itens = []
        for item in self.last_results:
            if isinstance(item, (tuple, list)):
                emoji, hora = item[0], item[1]
                itens.append(f"{emoji}<i>{hora}</i>")
            else:
                itens.append(str(item))

        # Quebra em linhas de 10 para facilitar leitura
        LINHA = 10
        linhas = []
        for i in range(0, len(itens), LINHA):
            chunk = itens[i:i + LINHA]
            linhas.append("  ".join(chunk))
        return "\n".join(linhas)

    def to_message(self, pattern: list, prediction: str, name: str,
                   regime_linha: str = "") -> str:
        emoji   = COLOR_LETTER_TO_EMOJI.get(prediction, "❓")
        pat_str = " → ".join(COLOR_LETTER_TO_EMOJI.get(str(c), str(c)) for c in pattern)
        if self.current_win_streak > 0:
            streak_txt = f"🔥 <b>{self.current_win_streak} wins seguidos</b>"
        elif self.current_loss_streak > 0:
            streak_txt = f"⚠️ <b>{self.current_loss_streak} losses seguidos</b>"
        else:
            streak_txt = "—"
        recent_raw    = self.last_results[-5:] if len(self.last_results) >= 5 else self.last_results
        recent        = [r[0] if isinstance(r, tuple) else r for r in recent_raw]
        wins_recentes = recent.count("✅")
        if len(recent) >= 5:
            temp = (f"🌡️ QUENTE — {wins_recentes}W/5" if wins_recentes >= 4 else
                    f"🌡️ FRIO — {wins_recentes}W/5"   if wins_recentes <= 1 else
                    f"🌡️ Neutro — {wins_recentes}W/5")
        else:
            temp = "🌡️ Poucos dados"

        extras = ""
        if regime_linha:
            extras += f"{regime_linha}\n"

        return (
            f"🏷️ <b>Padrão VP [{name}]</b>\n"
            f"📋 {pat_str} → {emoji}\n\n"
            f"✅ <b>{self.wins}W</b>  ❌ <b>{self.losses}L</b>  📊 <b>{self.accuracy:.0f}%</b>\n"
            f"🔥 Streak: {streak_txt}  |  🏆 Recorde: {self.max_win_streak}W\n"
            f"{temp}\n"
            f"{extras}"
            f"📅 Hoje: <b>{self.today_count}</b>  🎯 Total: <b>{self.total_count}</b>\n"

            f"📈 Últimos 30:\n{self.visual_history}"
        )


@dataclass
class BetState:
    active: bool = False
    color: Optional[str] = None
    pattern: Optional[list] = None
    source: Optional[str] = None
    gale_current: int = 0
    gale_max: int = 2
    origem: str = "padrao"
    valor_apostado: float = 0.0
    cores_saidas: list = field(default_factory=list)  # cores que saíram durante o gale

    def reset(self) -> None:
        self.active         = False
        self.color          = None
        self.pattern        = None
        self.source         = None
        self.gale_current   = 0
        self.gale_max       = 2
        self.origem         = "padrao"
        self.valor_apostado = 0.0
        self.cores_saidas   = []

    def can_gale(self) -> bool:  return self.gale_current < self.gale_max
    def next_gale(self) -> None: self.gale_current += 1

    def simular_gale2(self) -> str:
        """
        Simula o que teria acontecido se o gale máximo fosse 2.
        Usa as cores que já saíram (cores_saidas) e a cor apostada.
        Retorna: 'WIN_G1', 'WIN_G2', 'LOSS' ou '' (sem dados)
        """
        if not self.color or not self.cores_saidas:
            return ""
        for i, cor in enumerate(self.cores_saidas):
            if cor == self.color:
                if i == 0:   return "WIN_G0"  # win direto
                if i == 1:   return "WIN_G1"  # win no gale 1
                if i == 2:   return "WIN_G2"  # win no gale 2
            # Branco não conta como loss
        if len(self.cores_saidas) >= 3:
            return "LOSS"
        return ""

    @property
    def gale_label(self) -> str:
        return f"Gale {self.gale_max}"


@dataclass
class ColorCooldown:
    win_streak: dict = field(default_factory=lambda: {"V": 0, "P": 0})
    last_win_color: Optional[str] = None
    global_cooldown_until: float = 0.0

    def register_win(self, color: str) -> None:
        if color not in ("V", "P"):
            return
        if self.last_win_color != color:
            self.win_streak = {"V": 0, "P": 0}
            self.win_streak[color] = 1
        else:
            self.win_streak[color] += 1
        self.last_win_color = color
        if self.win_streak[color] >= WIN_STREAK_LIMIT:
            self.global_cooldown_until = asyncio.get_event_loop().time() + COLOR_COOLDOWN_SECONDS
            self.win_streak = {"V": 0, "P": 0}
            self.last_win_color = None

    def register_loss(self, color: str) -> None:
        self.win_streak     = {"V": 0, "P": 0}
        self.last_win_color = None

    def is_blocked(self) -> bool:
        return (self.global_cooldown_until - asyncio.get_event_loop().time()) > 0

    def remaining_seconds(self) -> int:
        return max(0, int(self.global_cooldown_until - asyncio.get_event_loop().time()))

    def streak_info(self) -> str:
        if self.last_win_color:
            cor = self.last_win_color
            n   = self.win_streak.get(cor, 0)
            em  = COLOR_LETTER_TO_EMOJI.get(cor, "")
            return f"🔥 Streak {em}: <b>{n}/{WIN_STREAK_LIMIT}</b>"
        return ""


class MarkovChain:
    COLORS       = ("V", "P")
    MIN_SAMPLES  = 8
    MIN_CONFIDENCE = 0.60

    def __init__(self, order: int = 3):
        self.order       = order
        self.transitions: dict = {}

    def feed(self, history: list) -> None:
        history_vp = [c for c in history if c in ("V", "P")]
        self.transitions.clear()
        for i in range(len(history_vp) - self.order):
            state      = tuple(history_vp[i:i + self.order])
            next_color = history_vp[i + self.order]
            if next_color not in self.COLORS:
                continue
            if state not in self.transitions:
                self.transitions[state] = {"V": 0, "P": 0}
            self.transitions[state][next_color] += 1

    def predict(self, history: list) -> Optional[dict]:
        history_vp = [c for c in history if c in ("V", "P")]
        if len(history_vp) < self.order:
            return None
        state  = tuple(history_vp[-self.order:])
        counts = self.transitions.get(state)
        if not counts:
            return None
        total  = sum(counts.values())
        if total < self.MIN_SAMPLES:
            return None
        probs          = {c: round(counts[c]/total, 4) for c in self.COLORS}
        probs["samples"] = total
        probs["state"]   = state
        return probs

    def confirm_signal(self, history: list, predicted_color: str) -> tuple:
        probs = self.predict(history)
        if probs is None:
            return True, 0.0, None
        conf       = probs.get(predicted_color, 0.0)
        confirmado = conf >= self.MIN_CONFIDENCE
        return confirmado, conf, probs

    def summary_str(self, history: list, predicted_color: str) -> str:
        confirmado, conf, probs = self.confirm_signal(history, predicted_color)
        if probs is None:
            return "🧮 Markov VP: <i>dados insuficientes</i>"
        emoji_color = COLOR_LETTER_TO_EMOJI.get(predicted_color, "❓")
        check   = "✅" if confirmado else "⚠️"
        v       = probs.get("V", 0)
        p       = probs.get("P", 0)
        samples = probs.get("samples", 0)
        return (
            f"🧮 <b>Markov VP</b> {check} {emoji_color} <b>{conf:.0%}</b>  "
            f"<i>🔴{v:.0%} ⚫{p:.0%} ({samples} amostras)</i>"
        )


class AnomalyDetector:
    WINDOW           = 30
    PAUSE_ROUNDS     = 10
    VOLATILITY_MAX   = 0.85
    DOMINANCE_MAX    = 0.80
    ENTROPY_MIN      = 0.55
    SESSION_LOSS_MAX = 0.40

    def __init__(self):
        self.paused_until_round: int = 0
        self.last_anomaly_type:  str = ""

    def is_paused(self, current_round: int) -> bool:
        return current_round < self.paused_until_round

    def pause(self, current_round: int, reason: str) -> None:
        self.paused_until_round = current_round + self.PAUSE_ROUNDS
        self.last_anomaly_type  = reason

    def remaining_rounds(self, current_round: int) -> int:
        return max(0, self.paused_until_round - current_round)

    def _volatility(self, history: list) -> float:
        w = [c for c in history[-self.WINDOW:] if c in ("V", "P")]
        if len(w) < 4: return 0.0
        return sum(1 for i in range(1, len(w)) if w[i] != w[i-1]) / (len(w) - 1)

    def _dominance(self, history: list) -> tuple:
        w = [c for c in history[-self.WINDOW:] if c in ("V", "P")]
        if not w: return None, 0.0
        counts   = {"V": w.count("V"), "P": w.count("P")}
        dominant = max(counts, key=counts.get)
        return dominant, counts[dominant] / len(w)

    def _entropy(self, history: list) -> float:
        w = [c for c in history[-self.WINDOW:] if c in ("V", "P")]
        if len(w) < 4: return 1.0
        total = len(w)
        ent   = 0.0
        for c in ("V", "P"):
            p = w.count(c) / total
            if p > 0:
                ent -= p * math.log2(p)
        return ent / math.log2(2)

    def _session_loss_rate(self, last_results: list) -> float:
        recent = last_results[-10:] if len(last_results) >= 10 else last_results
        if not recent: return 0.0
        return recent.count("❌") / len(recent)

    def analyze(self, history: list, session_results: list, current_round: int) -> tuple:
        if len(history) < self.WINDOW:
            return False, "", {}
        details = {}
        vol = self._volatility(history)
        details["volatilidade"] = vol
        if vol > self.VOLATILITY_MAX:
            return True, f"volatilidade_alta ({vol:.0%})", details
        dominant_color, dom_pct = self._dominance(history)
        details["dominancia"] = (dominant_color, dom_pct)
        if dom_pct > self.DOMINANCE_MAX:
            cor_emoji = {"V": "🔴", "P": "⚫"}.get(dominant_color, "")
            return True, f"dominancia_{dominant_color} ({cor_emoji} {dom_pct:.0%})", details
        ent = self._entropy(history)
        details["entropia"] = ent
        if ent < self.ENTROPY_MIN:
            return True, f"entropia_baixa ({ent:.0%})", details
        loss_rate = self._session_loss_rate(session_results)
        details["loss_rate_sessao"] = loss_rate
        if loss_rate >= self.SESSION_LOSS_MAX:
            return True, f"loss_rate_alto ({loss_rate:.0%} nos últimos 10)", details
        return False, "", details


class MineradorPadroes:
    """
    Minerador com rodízio de critérios: a cada execução alterna entre
    Nível-11 (≥11 oc.), Nível-12 (≥12 oc.) e Nível-13 (≥13 oc.).
    Após cada nível, escolhe e mantém o conjunto com maior % de acertos.
    Também coleta histórico em paralelo (pages em lotes) para mais velocidade.
    """

    def __init__(self, bot_ref):
        self.bot                        = bot_ref
        self._lock                      = asyncio.Lock()
        self._rodando                   = False
        self._ultima_mineracao: float   = 0.0
        self._nivel_idx: int            = 0          # rodízio entre MINERADOR_NIVEIS
        # Rastreamento de desempenho por nível para escolher o melhor
        self._nivel_stats: dict         = {
            n["label"]: {"wins": 0, "total": 0} for n in MINERADOR_NIVEIS
        }

    # ── Nível atual em rodízio ─────────────────────────────────────
    @property
    def _nivel_atual(self) -> dict:
        return MINERADOR_NIVEIS[self._nivel_idx % len(MINERADOR_NIVEIS)]

    def _avancar_nivel(self) -> None:
        self._nivel_idx = (self._nivel_idx + 1) % len(MINERADOR_NIVEIS)

    def _melhor_nivel(self) -> str:
        """Retorna o label do nível com maior winrate (mín. 5 entradas)."""
        candidatos = {
            label: s for label, s in self._nivel_stats.items()
            if s["total"] >= 5
        }
        if not candidatos:
            return self._nivel_atual["label"]
        return max(candidatos, key=lambda k: candidatos[k]["wins"] / candidatos[k]["total"])

    def registrar_resultado_nivel(self, label: str, win: bool) -> None:
        if label in self._nivel_stats:
            self._nivel_stats[label]["total"] += 1
            if win:
                self._nivel_stats[label]["wins"] += 1

    async def rodar_se_necessario(self) -> None:
        agora = time.time()
        if agora - self._ultima_mineracao < MINERADOR_INTERVALO_HORAS * 3600:
            return
        if self._rodando:
            return
        asyncio.create_task(self._executar())

    async def _executar(self) -> None:
        self._rodando = True
        nivel = self._nivel_atual
        melhor = self._melhor_nivel()
        log.info(
            f"🔍 MINERADOR VP: nível={nivel['label']} | melhor={melhor} | "
            f"tamanhos=5-6 | ≥90% | ≥{nivel['ocorrencias']} ocorrências"
        )
        try:
            historico = await self._coletar_historico()
            if len(historico) < 200:
                log.warning("MINERADOR VP: histórico insuficiente.")
                return
            resultados = self._minerar(historico, nivel)
            if resultados:
                adicionados = await self._salvar(resultados)
                self.bot.patterns_a = BlazeBot._load_patterns("padroes_lista_A_normal.json")
                self.bot.patterns_b = BlazeBot._load_patterns("padroes_lista_B_top.json")
                self.bot.patterns_c = BlazeBot._load_patterns("padroes_lista_C_elite.json")
                self.bot.patterns_d = BlazeBot._load_patterns("padroes_lista_D_origem.json")
                total_pads = (len(self.bot.patterns_a) + len(self.bot.patterns_b) +
                              len(self.bot.patterns_c) + len(self.bot.patterns_d))
                if adicionados > 0:
                    await self.bot._send_async(
                        f"🔍 <b>Minerador</b> — <b>{adicionados}</b> novos padrões  "
                        f"│  Total: <b>{total_pads}</b>\n"
                        f"⏱️ Monitorando próximos <b>4 sinais</b> pós-mineração..."
                    )
                    # ── Inicia rastreamento dos 6 próximos sinais ──
                    _pos_mineracao.iniciar_ciclo(nivel["label"], adicionados)
                log.info(
                    f"MINERADOR VP concluído | {adicionados} novos | total={total_pads}"
                )
            else:
                log.info(f"MINERADOR VP ({nivel['label']}) — nenhum padrão novo.")
            self._avancar_nivel()
            self._ultima_mineracao = time.time()
        except Exception as e:
            log.error(f"MINERADOR VP erro: {e}")
        finally:
            self._rodando = False

    async def _coletar_historico(self) -> list:
        """Coleta histórico em paralelo (lotes de 10 páginas) para maior velocidade."""
        color_map = {0: "B", 1: "V", 2: "P"}
        await self.bot._ensure_session()
        paginas = list(range(1, MINERADOR_PAGINAS + 1))
        LOTE    = 10   # páginas por lote paralelo

        historico_raw: dict[int, list] = {}

        async def _buscar(pagina: int) -> None:
            url = (f"{self.bot.cfg.url}/api/singleplayer-originals/originals"
                   f"/roulette_games/recent/1?page={pagina}")
            try:
                async with self.bot._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status != 200:
                        return
                    data = await r.json()
                    if not data:
                        return
                    historico_raw[pagina] = [
                        color_map.get(item.get("color"), "?")
                        for item in data
                        if color_map.get(item.get("color"), "?") != "?"
                    ]
            except Exception as e:
                log.warning(f"MINERADOR VP página {pagina}: {e}")

        # Dispara lotes em paralelo
        for inicio in range(0, len(paginas), LOTE):
            lote = paginas[inicio:inicio + LOTE]
            await asyncio.gather(*[_buscar(p) for p in lote])
            await asyncio.sleep(0.05)   # pausa mínima entre lotes

        # Reconstrói em ordem
        historico = []
        for p in sorted(historico_raw.keys()):
            historico.extend(historico_raw[p])

        historico.reverse()
        historico_vp = [c for c in historico if c in ("V", "P")]
        log.info(f"MINERADOR VP: {len(historico)} rodadas → {len(historico_vp)} VP")
        return historico_vp

    def _minerar(self, historico: list, nivel: dict) -> dict:
        min_oc  = nivel["ocorrencias"]
        min_wr  = nivel["winrate"]
        resultados = {}
        for tamanho in MINERADOR_TAMANHOS:
            contagem: dict = {}
            for i in range(len(historico) - tamanho):
                segmento = tuple(historico[i:i + tamanho])
                proximo  = historico[i + tamanho]
                if proximo not in ("V", "P"):
                    continue
                chave           = (segmento, proximo)
                contagem[chave] = contagem.get(chave, 0) + 1

            padroes_unicos = set(k[0] for k in contagem)
            for padrao in padroes_unicos:
                totais      = {pred: contagem.get((padrao, pred), 0) for pred in ("V", "P")}
                total_apars = sum(totais.values())
                if total_apars < min_oc:
                    continue
                melhor_pred = max(totais, key=totais.get)
                wins        = totais[melhor_pred]
                winrate     = wins / total_apars
                if winrate >= min_wr and wins >= min_oc:
                    chave_final = (padrao, melhor_pred)
                    if (chave_final not in resultados or
                            resultados[chave_final]["winrate"] < winrate):
                        resultados[chave_final] = {
                            "wins":    wins,
                            "losses":  total_apars - wins,
                            "total":   total_apars,
                            "winrate": winrate,
                            "nivel":   nivel["label"],
                        }
        log.info(
            f"MINERADOR VP ({nivel['label']}): {len(resultados)} padrões "
            f"(≥{min_wr*100:.0f}%, ≥{min_oc} oc.)"
        )
        return resultados

    async def _salvar(self, resultados: dict) -> int:
        mapa = {
            "padroes_lista_C_elite.json": lambda s: s["winrate"] >= 1.00 and s["total"] >= 11,
            "padroes_lista_B_top.json":   lambda s: s["winrate"] >= 1.00 and s["total"] >= 11,
            "padroes_lista_A_normal.json":       lambda s: s["winrate"] >= 1.00 and s["total"] >= 11,
            "padroes_lista_D_origem.json":  lambda s: s["winrate"] >= 1.00 and s["total"] >= 11,
        }
        total_adicionados = 0
        async with self._lock:
            for arquivo, criterio in mapa.items():
                try:
                    try:
                        with open(arquivo, "r", encoding="utf-8") as f:
                            existentes = json.load(f)
                    except Exception:
                        existentes = []
                    adicionados = 0
                    for (padrao, pred), stats in resultados.items():
                        if not criterio(stats):
                            continue
                        entrada = [list(padrao), pred]
                        if entrada not in existentes:
                            existentes.append(entrada)
                            adicionados += 1
                    existentes.sort(key=lambda x: len(x[0]), reverse=True)
                    tmp = arquivo + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(existentes, f, indent=2, ensure_ascii=False)
                    os.replace(tmp, arquivo)
                    total_adicionados += adicionados
                    log.info(f"MINERADOR VP: {arquivo} — {adicionados} novos (total: {len(existentes)})")
                except Exception as e:
                    log.error(f"MINERADOR VP salvar {arquivo}: {e}")
        return total_adicionados


# ══════════════════════════════════════════════════════════════════
# POS-MINERAÇÃO TRACKER
# Registra os 4 primeiros sinais após cada mineração e salva JSON
# com: resultado, cor, gale, padrão, hora, lista, nome
# Arquivo: pos_mineracao_stats.json
# ══════════════════════════════════════════════════════════════════

class PosMineracaoTracker:
    """
    Após cada mineração (manual ou automática), monitora os próximos
    4 sinais e registra tudo num JSON histórico.

    Para cada ciclo de mineração salva:
      mineracao_id    : timestamp da mineração
      hora_mineracao  : HH:MM da mineração
      nivel           : nível usado (Nível-11/12/13)
      novos_padroes   : quantos padrões novos foram adicionados
      sinais[]        : lista dos próximos 4 sinais com detalhes completos

    Cada sinal contém:
      seq             : número do sinal (1 a 6)
      hora            : HH:MM:SS do sinal
      padrao_nome     : nome do padrão [MELAMAROR]
      padrao_cores    : sequência de cores ex: PPVPPV
      prediction      : cor prevista (V ou P)
      lista           : A/B/C/D
      resultado       : WIN / LOSS / WIN_GALE1 / WIN_GALE2
      win             : true/false
      win_direto      : true/false (sem gale)
      gale            : 0/1/2
      cor_saiu        : cor real que saiu
    """

    DB_FILE  = "pos_mineracao_stats.json"
    MAX_SINAIS = 10  # monitora os 10 primeiros sinais após cada mineração

    def __init__(self):
        self._ciclos: list       = []   # histórico completo de ciclos
        self._ciclo_ativo: dict  = {}   # ciclo em andamento
        self._monitorando: bool  = False
        self._load()

    def _load(self):
        if not os.path.exists(self.DB_FILE):
            return
        try:
            with open(self.DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._ciclos = data.get("ciclos", [])
            log.info(f"PosMineracaoTracker: {len(self._ciclos)} ciclos carregados")
        except Exception as e:
            log.error(f"PosMineracaoTracker load: {e}")

    def _save(self):
        try:
            with open(self.DB_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "ciclos": self._ciclos,
                    "total_ciclos": len(self._ciclos),
                    "ultima_atualizacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"PosMineracaoTracker save: {e}")

    def iniciar_ciclo(self, nivel_label: str, novos_padroes: int) -> None:
        """Inicia um novo ciclo de monitoramento após uma mineração."""
        if self._ciclo_ativo:
            # Fecha ciclo anterior incompleto
            self._ciclo_ativo["encerrado"] = "incompleto"
            self._ciclos.append(self._ciclo_ativo)

        self._ciclo_ativo = {
            "mineracao_id":  int(time.time()),
            "hora_mineracao": datetime.now().strftime("%H:%M %d/%m/%Y"),
            "nivel":          nivel_label,
            "novos_padroes":  novos_padroes,
            "sinais":         [],
            "encerrado":      False,
        }
        self._monitorando = True
        log.info(f"PosMineracao: ciclo iniciado | nível={nivel_label} | novos={novos_padroes}")

    @property
    def monitorando(self) -> bool:
        return self._monitorando and bool(self._ciclo_ativo)

    @property
    def sinais_restantes(self) -> int:
        if not self._ciclo_ativo:
            return 0
        return max(0, self.MAX_SINAIS - len(self._ciclo_ativo.get("sinais", [])))

    def registrar_sinal(
        self,
        padrao_nome: str,
        padrao_cores: list,
        prediction: str,
        lista: str,
        resultado: str,     # "WIN" | "LOSS" | "GALE"
        gale: int,
        cor_saiu: str,
    ) -> None:
        """Registra resultado de um sinal no ciclo ativo."""
        if not self._monitorando or not self._ciclo_ativo:
            return
        if resultado == "GALE":
            return  # aguarda WIN ou LOSS final

        sinais = self._ciclo_ativo["sinais"]
        seq    = len(sinais) + 1

        CE = {"V": "🔴", "P": "⚫", "B": "⚪"}
        cores_str = "".join(CE.get(c, c) for c in padrao_cores)
        pred_emoji = CE.get(prediction, prediction)
        saiu_emoji = CE.get(cor_saiu, cor_saiu)

        win        = resultado == "WIN"
        win_direto = win and gale == 0

        if win and gale == 0:   res_label = "✅ WIN direto"
        elif win and gale == 1: res_label = "✅ WIN Gale 1"
        elif win and gale == 2: res_label = "✅ WIN Gale 2"
        else:                   res_label = f"❌ LOSS (gale {gale})"

        sinais.append({
            "seq":         seq,
            "hora":        datetime.now().strftime("%H:%M:%S"),
            "padrao_nome": padrao_nome,
            "padrao_cores": "".join(padrao_cores),
            "prediction":  prediction,
            "lista":       lista,
            "resultado":   res_label,
            "win":         win,
            "win_direto":  win_direto,
            "gale":        gale,
            "cor_saiu":    cor_saiu,
        })

        log.info(
            f"PosMineracao sinal {seq}/{self.MAX_SINAIS} | "
            f"[{padrao_nome}] {cores_str}→{pred_emoji} | "
            f"{res_label} | saiu={saiu_emoji}"
        )

        if seq >= self.MAX_SINAIS:
            self._fechar_ciclo()

    def _fechar_ciclo(self) -> None:
        """Fecha o ciclo atual e salva."""
        if not self._ciclo_ativo:
            return
        sinais  = self._ciclo_ativo.get("sinais", [])
        wins    = sum(1 for s in sinais if s["win"])
        losses  = len(sinais) - wins
        w_dir   = sum(1 for s in sinais if s["win_direto"])
        w_gale  = wins - w_dir
        verm    = sum(1 for s in sinais if s["prediction"] == "V")
        preto   = sum(1 for s in sinais if s["prediction"] == "P")

        self._ciclo_ativo["encerrado"]   = True
        self._ciclo_ativo["resumo"] = {
            "total":       len(sinais),
            "wins":        wins,
            "losses":      losses,
            "win_direto":  w_dir,
            "win_gale":    w_gale,
            "accuracy":    round(wins / max(1, len(sinais)) * 100, 1),
            "sinais_V":    verm,
            "sinais_P":    preto,
        }
        self._ciclos.append(self._ciclo_ativo)
        self._ciclo_ativo  = {}
        self._monitorando  = False
        self._save()
        log.info(
            f"PosMineracao: ciclo encerrado | "
            f"{wins}W/{losses}L ({self._ciclos[-1]['resumo']['accuracy']}%)"
        )

    def relatorio_ultimo(self) -> str:
        """
        Relatório do ciclo mais recente — completo OU parcial.
        Mostra todos os sinais já registrados, mesmo sem completar os 10.
        """
        CE = {"V": "🔴", "P": "⚫", "B": "⚪"}

        # Prioridade: ciclo ativo (parcial) > último completo
        ciclo_parcial = self._ciclo_ativo if self._ciclo_ativo else None
        ciclos_ok     = [c for c in self._ciclos if c.get("encerrado") is True]

        if ciclo_parcial and ciclo_parcial.get("sinais"):
            c       = ciclo_parcial
            sinais  = c.get("sinais", [])
            parcial = True
        elif ciclos_ok:
            c       = ciclos_ok[-1]
            sinais  = c.get("sinais", [])
            parcial = False
        else:
            if self._monitorando:
                return (
                    f"📊 <b>Pós-Mineração</b> — monitorando...\n"
                    f"Aguardando primeiros sinais após a mineração.\n"
                    f"Restantes: <b>{self.sinais_restantes}/{self.MAX_SINAIS}</b>"
                )
            return "📊 <b>Pós-Mineração</b>: ainda sem sinais.\nUse /minerar para iniciar."

        wins     = sum(1 for s in sinais if s["win"])
        losses   = len(sinais) - wins
        w_dir    = sum(1 for s in sinais if s["win_direto"])
        w_gale   = wins - w_dir
        sinais_v = sum(1 for s in sinais if s["prediction"] == "V")
        sinais_p = sum(1 for s in sinais if s["prediction"] == "P")
        acc      = round(wins / max(1, len(sinais)) * 100, 1)

        linhas = []
        for s in sinais:
            cores = "".join(CE.get(x, x) for x in s["padrao_cores"])
            pred  = CE.get(s["prediction"], s["prediction"])
            linhas.append(
                f"  {s['seq']}. <b>[{s['padrao_nome']}]</b> "
                f"{cores}→{pred}  "
                f"{s['resultado']}  "
                f"🕐{s['hora']}  "
                f"Lista {s['lista']}"
            )

        status_header = (
            f"⏳ <b>Em andamento</b> — {len(sinais)}/{self.MAX_SINAIS} sinais\n"
            if parcial else
            f"✅ <b>Ciclo completo</b> — {len(sinais)} sinais\n"
        )

        return (
            f"📊 <b>Pós-Mineração — {c.get('hora_mineracao','—')}</b>\n"
            f"{'─' * 22}\n"
            f"{status_header}"
            f"⛏️ Nível: <b>{c.get('nivel','—')}</b>  │  "
            f"Novos: <b>{c.get('novos_padroes', 0)}</b>\n\n"
            f"✅ Wins: <b>{wins}</b>  ❌ Losses: <b>{losses}</b>  📊 <b>{acc}%</b>\n"
            f"🎯 Win direto: <b>{w_dir}</b>  ♻️ Win c/ gale: <b>{w_gale}</b>\n"
            f"🔴 Sinais V: <b>{sinais_v}</b>  ⚫ Sinais P: <b>{sinais_p}</b>\n"
            f"{'─' * 22}\n"
            + ("\n".join(linhas) if linhas else "<i>Nenhum sinal ainda</i>") +
            f"\n{'─' * 22}"
        )

    def relatorio_historico(self) -> str:
        """Resumo de todos os ciclos anteriores."""
        ciclos_ok = [c for c in self._ciclos if c.get("encerrado") is True]
        if not ciclos_ok:
            return "📊 <b>Histórico Pós-Mineração</b>: nenhum ciclo completo."

        total_w = sum(c["resumo"]["wins"]   for c in ciclos_ok)
        total_l = sum(c["resumo"]["losses"] for c in ciclos_ok)
        total_s = total_w + total_l
        acc_geral = round(total_w / max(1, total_s) * 100, 1)
        w_dir_tot = sum(c["resumo"]["win_direto"] for c in ciclos_ok)

        linhas = []
        for i, c in enumerate(ciclos_ok[-10:], 1):  # últimos 10
            r  = c["resumo"]
            em = "✅" if r["accuracy"] >= 70 else ("⚠️" if r["accuracy"] >= 50 else "❌")
            linhas.append(
                f"  {em} {c['hora_mineracao']}  "
                f"{r['wins']}W/{r['losses']}L  "
                f"<b>{r['accuracy']}%</b>  "
                f"[{c['nivel']}]"
            )

        return (
            f"📊 <b>Histórico Pós-Mineração</b>\n"
            f"{'─' * 22}\n"
            f"Ciclos completos: <b>{len(ciclos_ok)}</b>\n"
            f"Total: <b>{total_w}W / {total_l}L</b>  📊 <b>{acc_geral}%</b>\n"
            f"Win direto: <b>{w_dir_tot}/{total_s}</b> "
            f"({round(w_dir_tot/max(1,total_s)*100)}%)\n\n"
            f"<b>Últimos 10 ciclos:</b>\n"
            + "\n".join(linhas)
        )


_pos_mineracao = PosMineracaoTracker()


class BlazeBot:
    def __init__(self, config_file: str = "config.ini"):
        self.cfg          = Config.from_file(config_file)
        self.stats        = Stats()
        self.bet          = BetState(gale_max=self.cfg.max_gale)
        self.cooldown     = ColorCooldown()
        self.ab           = ABCTracker()
        self.gestor_banca = GestorBancaProgressiva(
            banca_inicial=self.cfg.banca_inicial,
            entrada_base=self.cfg.entrada_base,
        )

        self.running: bool               = True
        self.protected: bool             = False
        self.last_status: Optional[str]  = None
        self.pending_msg_id: Optional[int]      = None
        self.last_matrix_msg_id: Optional[int]  = None
        self.last_matrix_time: float     = 0.0
        self.last_relatorio_3min: float  = 0.0  # timer do relatório a cada 3 min

        # ── Anti-sinal-duplo: lock assíncrono + timestamp ─────────
        # Garante que apenas UM sinal seja processado por vez,
        # mesmo se a API piscar "waiting" duas vezes seguidas.
        self._signal_lock: asyncio.Lock  = asyncio.Lock()
        self._last_signal_ts: float      = 0.0   # epoch do último sinal enviado
        self._min_signal_interval: float = 8.0   # mín. 8s entre sinais consecutivos
        self._last_waiting_ts: float     = 0.0   # epoch do último "waiting" recebido

        # ── Rastreamento de cor dominante (padrão 5 ou 6 iguais) ──
        self.cor_dom_wins:  int  = 0
        self.cor_dom_losses: int = 0
        self.cor_dom_ultimo: Optional[str] = None   # cor detectada no sinal atual

        self.rodadas_cooldown_loss: int  = 0
        self.modo_conservador_ate: int   = 0
        self.last_loss_pattern_ks: str   = ""
        self.hora_ruim_bloqueada_ate: float = 0.0
        self.janela_bloqueada_ate: float = 0.0
        self.pausa_consec_loss_ate: float = 0.0  # não usado mais
        self._bloqueia_proximo_sinal: bool = False  # bloqueia 1 sinal após 2 losses
        self._ultimo_score: int = 0  # score do último sinal gerado

        # ── Sistema de 3 Categorias ──────────────────────────────
        # Rastreia a categoria do último sinal e se deu loss
        # para decidir qual categoria aceitar no próximo sinal
        # ── Minerador em Tempo Real ──────────────────────────────
        self._rt_patterns: list = []          # padrões minerados ao vivo (na memória)
        self._rt_rodadas_desde_mine: int = 0  # contador de rodadas desde última mineração
        self._rt_ultima_mine_ts: str = ""     # timestamp da última mineração RT
        self._rt_total_minerados: int = 0     # total acumulado de padrões minerados RT

        # ── Sistema de Categorias por Resultado ─────────────────
        # CAT1 = ganhou na 1ª  | CAT2 = 1 loss | CAT3 = 2 losses
        # WIN em qualquer → volta CAT1
        self._cat_atual: int = 1        # categoria atual do bot (1, 2 ou 3)
        self._cat_losses_seguidos: int = 0  # losses consecutivos desde último win
        self._cat_motivo: str = "início"    # motivo da categoria atual

        self.score_minimo_atual: int = SCORE_MIN_INICIAL

        import concurrent.futures
        self._tg_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="tg")

        log.info("🔴⚫ MODO VP — Padrões 5-6 | 11 testes | 90%")
        self.patterns_a = self._load_patterns("padroes_lista_A_normal.json")
        self.patterns_b = self._load_patterns("padroes_lista_B_top.json")
        self.patterns_c = self._load_patterns("padroes_lista_C_elite.json")
        self.patterns_d = self._load_patterns("padroes_lista_D_origem.json")
        log.info(
            f"Padrões VP: A({len(self.patterns_a)}) B({len(self.patterns_b)}) "
            f"C({len(self.patterns_c)}) D({len(self.patterns_d)})"
        )

        self.pattern_records: dict = {}
        self.pattern_names         = PatternNameRegistry()

        # ── Cache de sucessores (carrega 1x, reutiliza em todos os sinais) ──
        # Preferência: v2 (contagem real 5/6 cores) > v1 (legado)
        self._sucessores_cache: dict = {}
        try:
            import json as _jsc
            _os_p = __import__("os").path
            _sf   = ("sucessores_padroes_v2.json"
                     if _os_p.exists("sucessores_padroes_v2.json")
                     else "sucessores_padroes.json")
            if _os_p.exists(_sf):
                with open(_sf, "r", encoding="utf-8") as _fh:
                    self._sucessores_cache = _jsc.load(_fh)
                log.info(f"🔮 Sucessores carregados ({_sf}): {len(self._sucessores_cache)} padrões")
            else:
                log.warning("🔮 Nenhum arquivo de sucessores encontrado")
        except Exception as _e:
            log.warning(f"🔮 Erro ao carregar sucessores: {_e}")

        # ── Confirmador pós-sinal ─────────────────────────────────
        # Após cada sinal, coleta as próximas rodadas VP.
        # Se nas próximas _confirma_max rodadas VP aparecerem
        # ≥ _confirma_min cores iguais à predição → CONFIRMADO ✅
        # Exemplo: enviou PVVPV→V. Próximas 5 VP = V P V P V → 3x V → ✅
        self._confirma_pred:   str  = ""    # cor predita no último sinal
        self._confirma_pat:    str  = ""    # padrão do sinal (ex: "PVVPV")
        self._confirma_nome:   str  = ""    # nome do padrão
        self._confirma_buffer: list = []    # cores VP coletadas após o sinal
        self._confirma_max:    int  = 5     # janela de observação (rodadas VP)
        self._confirma_min:    int  = 3     # mínimo de cores iguais p/ confirmar
        self._confirma_ativo:  bool = False # True enquanto monitora
        self.global_round: int     = 0

        # ── Criados ANTES de _load_pattern_db para evitar AttributeError ──
        self.history_buffer: list  = []
        self.markov                = MarkovChain(order=3)
        self.anomaly               = AnomalyDetector()
        self.regime                = RegimeDetector()
        self.entropia_guard        = EntropiaHashGuard()
        self.autocorr_pearson      = AutoCorrelacaoPearson()
        self.bias_pos_branco       = BiasPósBranco()

        self._load_pattern_db()

        self.pattern_loss_until: dict = {}

        self.auto_learner_a = AutoLearner(
            "padroes_lista_A_normal.json",       AUTO_LEARN_DB_FILE_A,
            AUTO_LEARN_MIN_ROUNDS_A,    AUTO_LEARN_MIN_ACCURACY_A,
            self.cfg.max_gale, "A")
        self.auto_learner_b = AutoLearner(
            "padroes_lista_B_top.json",   AUTO_LEARN_DB_FILE_B,
            AUTO_LEARN_MIN_ROUNDS_B,    AUTO_LEARN_MIN_ACCURACY_B,
            self.cfg.max_gale, "B")
        self.auto_learner_c = AutoLearner(
            "padroes_lista_C_elite.json", AUTO_LEARN_DB_FILE_C,
            AUTO_LEARN_MIN_ROUNDS_C,    AUTO_LEARN_MIN_ACCURACY_C,
            self.cfg.max_gale, "C")
        self.auto_learner_d = AutoLearner(
            "padroes_lista_D_origem.json",  AUTO_LEARN_DB_FILE_D,
            AUTO_LEARN_MIN_ROUNDS_D,    AUTO_LEARN_MIN_ACCURACY_D,
            self.cfg.max_gale, "D")

        self.prev_pattern: Optional[list]   = None
        self.prev_prediction: Optional[str] = None
        self.prev_source: Optional[str]     = None

        self._session: Optional[aiohttp.ClientSession] = None
        self._tg_client: Optional[TelegramClient] = None
        self._tg_entity = None

        self._recent_cache: Optional[dict] = None
        self._recent_cache_ts: float = 0.0
        self._recent_cache_ttl: float = 2.0  # cache de 2s: mais responsivo

        self.bot = telebot.TeleBot(self.cfg.token, parse_mode="HTML")
        self._register_commands()
        self.minerador = MineradorPadroes(self)
        # ── Fila de envio assíncrono: garante ordem e evita flood do Telegram ──
        self._tg_queue: asyncio.Queue = asyncio.Queue(maxsize=50)

        self.autobet: Optional[BlazeAutobet] = None
        if self.cfg.autobet.ativo:
            self.autobet = BlazeAutobet(
                base_url      = self.cfg.url,
                email         = self.cfg.blaze_email,
                password      = self.cfg.blaze_password,
                cfg           = self.cfg.autobet,
                session_getter= self._ensure_session_obj,
            )
            modo_txt = "🔵 DRY-RUN (simulação)" if self.cfg.autobet.dry_run else "🟢 BANCA REAL"
            log.info(
                f"🎰 AutoBet ATIVO | {modo_txt} | "
                f"base=R${self.cfg.autobet.aposta_base:.2f} | "
                f"niveis={self.cfg.autobet.max_niveis} | "
                f"stop=R${self.cfg.autobet.stop_loss:.2f} | "
                f"gain=R${self.cfg.autobet.take_profit:.2f}"
            )

        # ── Vermelho Engine ────────────────────────────────────────
        if _VERMELHO_ENGINE_DISPONIVEL:
            try:
                salvar_padroes_vermelho_json()
                self.patterns_a = self._load_patterns("padroes_lista_A_normal.json")
                self.patterns_b = self._load_patterns("padroes_lista_B_top.json")
                self.patterns_c = self._load_patterns("padroes_lista_C_elite.json")
                self.patterns_d = self._load_patterns("padroes_lista_D_origem.json")
            except Exception as _ve_init_err:
                log.warning(f"VermelhoEngine JSON init: {_ve_init_err}")
            self.vermelho_integrador = VermelhoBotIntegrator(self)
            log.info("🔴 VermelhoEngine integrado ao BlazeBot")
        else:
            self.vermelho_integrador = None

    async def _ensure_session_obj(self) -> aiohttp.ClientSession:
        await self._ensure_session()
        return self._session

    @staticmethod
    def _load_patterns(path: str) -> list:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            filtered = []
            for item in data:
                if isinstance(item, list) and len(item) == 2:
                    pattern, pred = item
                    if pred not in ("V", "P"):
                        continue
                    if not all(c in ("V", "P") for c in pattern):
                        continue
                    size = len(pattern)
                    if size not in (5, 6):
                        continue
                    filtered.append(item)
            filtered.sort(key=lambda x: len(x[0]), reverse=True)
            return filtered
        except FileNotFoundError:
            return []
        except Exception as e:
            log.error(f"Erro ao carregar '{path}': {e}")
            return []

    async def _ensure_session(self) -> None:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                ssl=False,
                limit=20,               # máx conexões simultâneas
                limit_per_host=10,      # máx por host
                keepalive_timeout=30,   # mantém conexão viva (evita reconectar)
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                connector_owner=True,
                json_serialize=lambda x, **kw: __import__('json').dumps(x, ensure_ascii=False),
            )

    async def _ensure_tg_client(self) -> bool:
        if self._tg_client and self._tg_client.is_connected():
            return True
        if not self.cfg.tg_api_id or not self.cfg.tg_api_hash:
            log.error("❌ Telethon: api_id/api_hash não configurados no config.ini [telegram]")
            return False
        try:
            self._tg_client = TelegramClient(
                "sessao_telegram_bot",
                self.cfg.tg_api_id,
                self.cfg.tg_api_hash,
            )
            await self._tg_client.start(phone=self.cfg.tg_phone or None)
            log.info("✅ Telethon MTProto conectado!")
            self._tg_entity = await self._tg_client.get_entity(self.cfg.chat_id)
            return True
        except Exception as e:
            log.error(f"❌ Telethon falhou ao conectar: {type(e).__name__}: {e!r}")
            self._tg_client = None
            return False

    async def _fetch(self, endpoint: str) -> Optional[dict]:
        await self._ensure_session()
        url = f"{self.cfg.url}/{endpoint}"
        try:
            # timeout agressivo: connect 2s, leitura 5s — Blaze responde rápido
            _to = aiohttp.ClientTimeout(connect=2, sock_read=5, total=7)
            async with self._session.get(url, timeout=_to) as r:
                if r.status != 200:
                    return None
                return await r.json(content_type=None)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            log.warning(f"_fetch {endpoint}: {type(e).__name__}")
            return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        if self._tg_client and self._tg_client.is_connected():
            await self._tg_client.disconnect()
        self._tg_executor.shutdown(wait=False)

    async def get_current(self) -> Optional[dict]:
        return await self._fetch(
            "api/singleplayer-originals/originals/roulette_games/current/1")

    async def get_recent(self) -> Optional[dict]:
        data = await self._fetch(
            "api/singleplayer-originals/originals/roulette_games/recent/1")
        if not data or not isinstance(data, list):
            return None
        items = []
        for i in data:
            color_letter = COLOR_API_TO_LETTER.get(i.get("color"), "?")
            try:
                created = datetime.strptime(
                    i["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                created = ""
            items.append({"color": color_letter, "value": i["roll"], "created_date": created})
        return {"items": items}

    async def get_recent_cached(self) -> Optional[dict]:
        agora = time.time()
        if (self._recent_cache is not None and
                agora - self._recent_cache_ts < self._recent_cache_ttl):
            return self._recent_cache
        resultado = await self.get_recent()
        if resultado is not None:
            self._recent_cache    = resultado
            self._recent_cache_ts = agora
        return resultado

    def invalidar_cache_recent(self) -> None:
        self._recent_cache    = None
        self._recent_cache_ts = 0.0

    async def get_status(self) -> tuple[Optional[str], Optional[int], Optional[str]]:
        current = await self.get_current()
        if not current:
            return None, None, None
        return (current.get("status"), current.get("roll"),
                COLOR_API_TO_LETTER.get(current.get("color"), "?"))

    async def _match_pattern(self, pattern: list, prediction: str) -> bool:
        res = await self.get_recent_cached()
        if not res or "items" not in res:
            return False
        items_vp         = [i for i in res["items"] if i["color"] in ("V", "P")]
        items_vp_reversed = items_vp[::-1]
        if len(pattern) > len(items_vp_reversed):
            return False
        segment = items_vp_reversed[-len(pattern):]
        for expected, actual in zip(pattern, segment):
            exp = str(expected).upper()
            got = str(actual["color"]).upper()
            if exp != "X" and got != exp:
                return False
        return True

    async def _search_in_list_all(self, patterns: list) -> list[tuple[list, str]]:
        matches = []
        for item in patterns:
            if isinstance(item, list) and len(item) == 2:
                pattern, prediction = item
                if prediction not in ("V", "P"):
                    continue
                if await self._match_pattern(pattern, prediction):
                    matches.append((pattern, prediction))
        return matches

    async def find_pattern(self) -> Optional[tuple[list, str, str, list]]:
        if self.cooldown.is_blocked():
            return None
        all_matches = []
        for patterns_list, source_label in [
            (self.patterns_c, "C"),
            (self.patterns_b, "B"),
            (self.patterns_a, "A"),
        ]:
            for pat, pred in await self._search_in_list_all(patterns_list):
                all_matches.append((pat, pred, source_label))
        if not all_matches:
            return None
        PRIORIDADE = {"C": 0, "B": 1, "A": 2, "D": 3}
        all_matches.sort(key=lambda m: PRIORIDADE[m[2]])
        pattern, prediction, source = all_matches[0]
        confirmadores = [all_matches[0]]
        log.info(f"VP MATCH ✅ | cor={prediction} | lista={source}")
        return pattern, prediction, source, confirmadores

    async def _tendencia_mercado_vp(self) -> str:
        res = await self.get_recent_cached()
        if not res or "items" not in res:
            return ""
        items_vp  = [i["color"] for i in res["items"] if i["color"] in ("V", "P")]
        ultimas10 = items_vp[:10]
        ultimas5  = items_vp[:5]
        if not ultimas10:
            return ""
        v10 = ultimas10.count("V"); p10 = ultimas10.count("P")
        v5  = ultimas5.count("V");  p5  = ultimas5.count("P")
        dom_e = "🔴" if v10 >= p10 else "⚫️"
        alt   = ""
        dom10 = "V" if v10 > p10 else "P"
        dom5c = "V" if v5  > p5  else "P"
        if dom10 != dom5c and abs(v5 - p5) >= 2:
            d5e = "🔴" if v5 >= p5 else "⚫️"
            alt = f" | 🔄 Alternando → {d5e}"
        return f"📊 Tendência VP: 🔴 {v10}×  ⚫️ {p10}× — <b>{dom_e} dominando</b>{alt}"

    def _evaluate_result(self, color_result: str) -> str:
        if color_result == self.bet.color:
            return "WIN"
        # ── Proteção Branco: branco = WIN automático (paga 14x) ───────
        if color_result == "B":
            return "WIN_BRANCO"
        if self.bet.can_gale():
            self.bet.next_gale()
            return "GALE"
        return "LOSS"

    def _get_pattern_ranking(self, ks: str) -> str:
        eligible    = {k: r for k, r in self.pattern_records.items() if r.total >= 3}
        if len(eligible) < 2 or ks not in eligible:
            return "⬜ Sem ranking ainda"
        sorted_recs = sorted(eligible.items(), key=lambda x: x[1].accuracy, reverse=True)
        for pos, (k, _) in enumerate(sorted_recs, start=1):
            if k == ks:
                medal = "🥇" if pos == 1 else ("🥈" if pos == 2 else ("🥉" if pos == 3 else "🏅"))
                return f"{medal} <b>#{pos} de {len(eligible)}</b> padrões"
        return "⬜ Sem ranking ainda"

    def _register_pattern_result(self, pattern: list, prediction: str,
                                  win: bool, gale_attempt: int = 0) -> None:
        key  = (tuple(pattern), prediction)
        ks   = PatternNameRegistry._key_str(key)
        if ks not in self.pattern_records:
            self.pattern_records[ks] = PatternRecord()
        rec  = self.pattern_records[ks]
        name = self.pattern_names.get_name(key)

        # ── Contabiliza resultado geral ────────────────────────────
        if win:
            rec.register_win(gale_attempt=gale_attempt)
            # Win → zera losses consecutivos de exclusão
            rec.losses_consecutivos_exclusao = 0
            self._registrar_loss_json(win=True)
            # Atualiza sistema de categorias
            self._atualizar_cat(win=True)
            # Acumula wins — zera a cada 10 (contador de saúde, só estatística)
            rec.wins_acumulados_exclusao += 1
            if rec.wins_acumulados_exclusao >= 10:
                rec.wins_acumulados_exclusao = 0
                log.info(f"📊 WINS CICLO [{name}] | 10 wins acumulados | contador zerado")
        else:
            rec.register_loss()
            # Bloqueio temporário de 1 min
            self.pattern_loss_until[ks] = time.time() + LOSS_BLOCK_IMEDIATO_SEG
            # Incrementa losses consecutivos para exclusão
            rec.losses_consecutivos_exclusao += 1
            # Atualiza sistema de categorias (loss)
            self._atualizar_cat(win=False)

        # ── Proteção: 2 losses consecutivos = bloqueia próximo sinal + registra ──
        if (CONSEC_LOSS_ALERTA and
                self.stats.consecutive_losses >= CONSEC_LOSS_LIMITE):
            self._bloqueia_proximo_sinal = True
            self._registrar_loss_json(win=False)
            log.warning(
                f"🛡️ {self.stats.consecutive_losses} LOSSES CONSECUTIVOS — "
                f"próximo sinal bloqueado (1 rodada limpa)"
            )
            self._fire(self._send_async(
                f"⚠️ <b>{self.stats.consecutive_losses} LOSSES CONSECUTIVOS</b>\n\n"
                f"🛡️ Próximo sinal <b>bloqueado</b> (aguardando 1 rodada limpa)\n"
                f"📊 Banca: <b>R$ {self.gestor_banca.banca_atual:.2f}</b>\n"
                f"📋 Registro salvo em <code>{LOSS_JSON_FILE}</code>\n"
                f"💡 Use /stats para ver o histórico."
            ))
        else:
            self._registrar_loss_json(win=False)

        # ── Exclusão: sempre 2 losses consecutivos = exclui ─────────
        deve_excluir   = False
        motivo_janela  = ""

        if rec.losses_consecutivos_exclusao >= 2:
            deve_excluir  = True
            motivo_janela = (
                f"❌ <b>2 losses consecutivos</b> — padrão excluído"
            )

        if deve_excluir:
            pat_str = " → ".join(
                COLOR_LETTER_TO_EMOJI.get(str(c), str(c)) for c in pattern)
            removed = any([
                self.auto_learner_a.remove_active_pattern(pattern, prediction),
                self.auto_learner_b.remove_active_pattern(pattern, prediction),
                self.auto_learner_c.remove_active_pattern(pattern, prediction),
                self.auto_learner_d.remove_active_pattern(pattern, prediction),
            ])
            if removed:
                self.patterns_a = self._load_patterns("padroes_lista_A_normal.json")
                self.patterns_b = self._load_patterns("padroes_lista_B_top.json")
                self.patterns_c = self._load_patterns("padroes_lista_C_elite.json")
                self.patterns_d = self._load_patterns("padroes_lista_D_origem.json")
                self._fire(self._send_async(
                    f"🗑️ <b>Padrão VP [{name}] EXCLUÍDO</b>\n"
                    f"📋 {pat_str} → {COLOR_LETTER_TO_EMOJI.get(prediction,'?')}\n"
                    f"⚠️ {motivo_janela}\n"
                    f"📊 Histórico: {rec.wins}W/{rec.losses}L ({rec.accuracy:.0f}%)"
                ))
            # Zera losses e wins acumulados
            rec.losses_consecutivos_exclusao = 0
            rec.wins_acumulados_exclusao     = 0
            self.prev_pattern = None; self.prev_prediction = None
            self._save_pattern_db()
            regime_ln = self.regime.linha_status()
            self._fire(self._send_async(rec.to_message(pattern, prediction, name,
                                                        regime_linha=regime_ln)))
            return

        self.prev_pattern    = list(pattern)
        self.prev_prediction = prediction
        self._save_pattern_db()
        regime_ln = self.regime.linha_status()
        self._fire(self._send_async(rec.to_message(pattern, prediction, name,
                                                    regime_linha=regime_ln)))

    def _remover_dois_padroes(self, pat_atual, pred_atual, name_atual,
                               pat_anterior, pred_anterior) -> None:
        removidos = []
        for pat, pred in [(pat_atual, pred_atual), (pat_anterior, pred_anterior)]:
            key  = (tuple(pat), pred)
            nome = self.pattern_names.get_name(key)
            removed = any([
                self.auto_learner_a.remove_active_pattern(pat, pred),
                self.auto_learner_b.remove_active_pattern(pat, pred),
                self.auto_learner_c.remove_active_pattern(pat, pred),
                self.auto_learner_d.remove_active_pattern(pat, pred),
            ])
            if removed:
                removidos.append((pat, pred, nome))
        if removidos:
            self.patterns_a = self._load_patterns("padroes_lista_A_normal.json")
            self.patterns_b = self._load_patterns("padroes_lista_B_top.json")
            self.patterns_c = self._load_patterns("padroes_lista_C_elite.json")
            self.patterns_d = self._load_patterns("padroes_lista_D_origem.json")
            linhas = []
            for pat, pred, nome in removidos:
                pat_str = " → ".join(
                    COLOR_LETTER_TO_EMOJI.get(str(c), str(c)) for c in pat)
                linhas.append(
                    f"🗑️ <b>[{nome}]</b> {pat_str} → {COLOR_LETTER_TO_EMOJI.get(pred,'?')}")
            self._send(
                f"⚠️ <b>EXCLUSÃO DUPLA VP</b>\n\n"
                f"2 losses seguidos\n{'━'*18}\n"
                + "\n".join(linhas) +
                f"\n{'━'*18}\n🔁 AutoLearner VP monitorando"
            )

    def _save_pattern_db(self) -> None:
        try:
            records_serial = {}
            for ks, rec in self.pattern_records.items():
                records_serial[ks] = {
                    "wins": rec.wins, "losses": rec.losses,
                    "current_win_streak": rec.current_win_streak,
                    "current_loss_streak": rec.current_loss_streak,
                    "max_win_streak": rec.max_win_streak,
                    "max_loss_streak": rec.max_loss_streak,
                    "best_accuracy": rec.best_accuracy,
                    "last_result": rec.last_result,
                    "today_count": rec.today_count, "total_count": rec.total_count,
                    "last_used": rec.last_used, "last_used_date": rec.last_used_date,
                    "wins_in_gale": rec.wins_in_gale,
                    "last_seen_round": rec.last_seen_round,
                    "gap_sum": rec.gap_sum, "gap_count": rec.gap_count,
                    "max_gap": rec.max_gap,
                    "hour_wins": rec.hour_wins, "hour_total": rec.hour_total,
                    "last_results": rec.last_results,
                    "entries_since_last_loss": rec.entries_since_last_loss,
                    "last_loss_entry": rec.last_loss_entry,
                    "wins_after_streak": rec.wins_after_streak,
                    "score_minimo_individual": rec.score_minimo_individual,
                    "losses_consecutivos_exclusao": rec.losses_consecutivos_exclusao,
                    "wins_acumulados_exclusao":     rec.wins_acumulados_exclusao,

                }
            data = {
                "records":  records_serial,
                "names":    self.pattern_names.to_dict(),
                "regime":   self.regime.to_dict(),
            }
            with open(PATTERN_DB_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"Erro ao salvar {PATTERN_DB_FILE}: {e}")

    def _load_pattern_db(self) -> None:
        if not os.path.exists(PATTERN_DB_FILE):
            return
        try:
            with open(PATTERN_DB_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return
            data = json.loads(content)
            for ks, rd in data.get("records", {}).items():
                rec = PatternRecord(
                    wins=rd.get("wins",0), losses=rd.get("losses",0),
                    current_win_streak=rd.get("current_win_streak",0),
                    current_loss_streak=rd.get("current_loss_streak",0),
                    max_win_streak=rd.get("max_win_streak",0),
                    max_loss_streak=rd.get("max_loss_streak",0),
                    best_accuracy=rd.get("best_accuracy",0.0),
                    last_result=rd.get("last_result",""),
                    today_count=rd.get("today_count",0),
                    total_count=rd.get("total_count",0),
                    last_used=rd.get("last_used",""),
                    last_used_date=rd.get("last_used_date",""),
                    wins_in_gale=rd.get("wins_in_gale",0),
                    last_seen_round=rd.get("last_seen_round",0),
                    gap_sum=rd.get("gap_sum",0), gap_count=rd.get("gap_count",0),
                    max_gap=rd.get("max_gap",0),
                    hour_wins=rd.get("hour_wins",{}), hour_total=rd.get("hour_total",{}),
                    last_results=rd.get("last_results",[]),
                    entries_since_last_loss=rd.get("entries_since_last_loss",0),
                    last_loss_entry=rd.get("last_loss_entry",0),
                    wins_after_streak=rd.get("wins_after_streak",{}),
                    score_minimo_individual=max(SCORE_MIN_FLOOR, min(rd.get("score_minimo_individual", SCORE_MIN_INICIAL), SCORE_MIN_TETO)),
                    losses_consecutivos_exclusao=rd.get("losses_consecutivos_exclusao", rd.get("janela_sinais_losses", 0)),
                    wins_acumulados_exclusao=rd.get("wins_acumulados_exclusao", 0),

                )
                self.pattern_records[ks] = rec
            self.pattern_names.from_dict(data.get("names",{}))
            if "regime" in data:
                self.regime.from_dict(data["regime"])
                log.info(f"RegimeDetector restaurado: {self.regime.regime}")
            # ── Reset automático de scores inflados acima do teto atual ──
            resetados = 0
            for rec in self.pattern_records.values():
                if rec.score_minimo_individual > SCORE_MIN_TETO:
                    rec.score_minimo_individual = SCORE_MIN_INICIAL
                    resetados += 1
            if resetados > 0:
                log.info(f"🔄 {resetados} scores individuais resetados para {SCORE_MIN_INICIAL} (estavam acima do teto {SCORE_MIN_TETO})")
            log.info(f"{PATTERN_DB_FILE} carregado ({len(self.pattern_records)} padrões)")
        except Exception as e:
            log.error(f"Erro ao carregar {PATTERN_DB_FILE}: {e}")

    def _register_commands(self) -> None:
        bot = self.bot
        cfg = self.cfg

        @bot.message_handler(commands=["start"])
        def cmd_start(message):
            if message.chat.id != cfg.chat_id: return
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                # ── Controle ──────────────────────────────────────
                InlineKeyboardButton("▶️ Iniciar",         callback_data="iniciar"),
                InlineKeyboardButton("⏸️ Pausar",          callback_data="parar"),
                # ── Estatísticas ──────────────────────────────────
                InlineKeyboardButton("📊 Estatísticas",    callback_data="stats"),
                InlineKeyboardButton("🔬 Comparativo AB",  callback_data="ab"),
                InlineKeyboardButton("💰 Banca",           callback_data="banca"),
                InlineKeyboardButton("🎰 AutoBet",         callback_data="autobet"),
                # ── Padrões e Mineração ───────────────────────────
                InlineKeyboardButton("⛏️ Minerar",         callback_data="minerar"),
                InlineKeyboardButton("📋 Padrões",         callback_data="padroes"),
                InlineKeyboardButton("🏆 Top 10",          callback_data="top10"),
                InlineKeyboardButton("📬 Pós-Mineração",   callback_data="posminera"),
                InlineKeyboardButton("🤖 AutoLearner",     callback_data="learner"),
                InlineKeyboardButton("🔍 Status Minerador",callback_data="minerador_status"),
                # ── Análise de mercado ────────────────────────────
                InlineKeyboardButton("🤖 Motor VP",        callback_data="motor"),
                InlineKeyboardButton("🌊 Regime",          callback_data="regime"),
                InlineKeyboardButton("📐 Kelly",           callback_data="kelly"),
                InlineKeyboardButton("💹 EV",              callback_data="ev"),
                InlineKeyboardButton("📊 F1-Score",        callback_data="f1"),
                InlineKeyboardButton("🔬 Bootstrap",       callback_data="bootstrap"),
                # ── Números ───────────────────────────────────────
                InlineKeyboardButton("🔢 Números Secos",   callback_data="numeros"),
                InlineKeyboardButton("📈 Frequentes",      callback_data="frequentes"),
                InlineKeyboardButton("🕐 Hora Favorita",   callback_data="horafavorita"),
                InlineKeyboardButton("🔗 Pares Secos",     callback_data="pares"),
                # ── Extras ────────────────────────────────────────
                InlineKeyboardButton("⚪ Branco",           callback_data="branco"),
                InlineKeyboardButton("⚪ Branco Stats",     callback_data="brancostats"),
                InlineKeyboardButton("⚪ Branco Hist",      callback_data="brancohist"),
                InlineKeyboardButton("🔄 Reset Score",     callback_data="resetscore"),
                InlineKeyboardButton("🔮 Sim. Gale 2",     callback_data="simgale"),
                InlineKeyboardButton("📋 Relatório",       callback_data="relatorio"),
                InlineKeyboardButton("🎰 Abrir Blaze",
                    url="https://blaze.bet.br/pt/games/double"),
            )
            total_pads = (len(self.patterns_a) + len(self.patterns_b) +
                          len(self.patterns_c) + len(self.patterns_d))
            ab_status = ""
            if self.autobet:
                modo_ab = "🔵 DRY-RUN" if cfg.autobet.dry_run else "🟢 BANCA REAL"
                ab_status = (
                    f"\n\n🎰 <b>AutoBet {modo_ab}</b>\n"
                    f"💰 Base: R${cfg.autobet.aposta_base:.2f} | Níveis: {cfg.autobet.max_niveis}\n"
                    f"🛑 Stop: R${cfg.autobet.stop_loss:.2f} | 🎯 Gain: R${cfg.autobet.take_profit:.2f}"
                )
            bot.send_message(
                cfg.chat_id,
                f"<b>🤖 BlazeBot VP</b>\n"
                f"<i>🔴 Vermelho + ⚫ Preto — Decisão Autônoma</i>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 <b>Banca:</b> R$ {self.gestor_banca.banca_atual:.2f} "
                f"(inicial: R$ {self.gestor_banca.banca_inicial:.2f})\n"
                f"📊 <b>Nível:</b> {self.gestor_banca.nivel_atual}/10"
                f" | Entrada: R$ {self.gestor_banca.get_valor_aposta():.2f}\n\n"
                f"Status: <b>{'✅ Rodando' if self.running else '⏸️ Pausado'}</b>\n"
                f"Max Gale: <b>{cfg.max_gale}</b> | Max Loss: <b>{cfg.max_loss_streak}</b>\n\n"
                f"📏 <b>Padrões VP: {total_pads}</b> (tam. 5-6 | ≥90% | ≥11 testes)\n"
                f"🅰️ A={len(self.patterns_a)} | 🅱️ B={len(self.patterns_b)} | "
                f"🏅 C={len(self.patterns_c)} | 📂 D={len(self.patterns_d)}\n\n"
                f"{self.regime.linha_status()}"
                f"{ab_status}",
                reply_markup=markup, parse_mode="HTML",
            )

        @bot.message_handler(commands=["categorias"])
        def cmd_categorias(message):
            """Mostra o estado atual do sistema de categorias."""
            em_atual  = self._cat_emoji(self._cat_atual)
            lbl_atual = self._cat_label(self._cat_atual)

            # Top 5 padrões por WR (>=3 entradas)
            CE = {"V": "🔴", "P": "⚫"}
            confiaveis = sorted(
                [(ks, rec) for ks, rec in self.pattern_records.items() if rec.total >= 3],
                key=lambda x: -x[1].accuracy
            )[:5]
            linhas_top = []
            for ks, rec in confiaveis:
                nome = self.pattern_names._map.get(ks, "?")
                try:
                    import json as _jc
                    parsed  = _jc.loads(ks)
                    pat_str = "".join(CE.get(c, c) for c in parsed[0])
                    pred    = CE.get(parsed[1], "?")
                except Exception:
                    pat_str = "?"; pred = "?"
                streak = f" 🔥{rec.current_win_streak}W" if rec.current_win_streak >= 2 else ""
                linhas_top.append(
                    f"  [{nome}] {pat_str}→{pred}  "
                    f"<b>{rec.accuracy:.0f}%</b> {rec.wins}W/{rec.losses}L{streak}"
                )
            top_txt = "\n".join(linhas_top) if linhas_top else "  <i>aguardando dados</i>"

            bot.send_message(message.chat.id,
                f"📊 <b>SISTEMA DE CATEGORIAS</b>\n"
                f"{'─'*22}\n"
                f"{em_atual} Agora em: <b>CAT{self._cat_atual} — {lbl_atual}</b>\n"
                f"💀 Losses seguidos: <b>{self._cat_losses_seguidos}</b>\n"
                f"💬 <i>{self._cat_motivo or 'início'}</i>\n"
                f"{'─'*22}\n"
                f"🥇 CAT1 PRIMEIRA  — WIN na 1ª → fica CAT1\n"
                f"🥈 CAT2 SEGUNDA   — 1 loss → sobe CAT2\n"
                f"🥉 CAT3 TERCEIRA  — 2 losses → sobe CAT3\n"
                f"✅ WIN em qualquer → volta CAT1\n"
                f"{'─'*22}\n"
                f"🏆 <b>Top 5 padrões (WR):</b>\n{top_txt}",
                parse_mode="HTML"
            )

        @bot.message_handler(commands=["losses"])
        def cmd_losses(message):
            """Resumo completo do JSON — wins, losses e sequências."""
            import json as _json
            try:
                with open(LOSS_JSON_FILE, "r", encoding="utf-8") as _f:
                    dados = _json.load(_f)
            except Exception:
                bot.send_message(message.chat.id,
                    "📋 Nenhum registro ainda.\nJogue alguns sinais primeiro.",
                    parse_mode="HTML")
                return

            hoje = __import__('datetime').datetime.now().strftime("%Y-%m-%d")
            rd   = dados.get("resumo_diario", {}).get(hoje, {})

            wins_hoje   = rd.get("wins",   0)
            losses_hoje = rd.get("losses", 0)
            wr_hoje     = rd.get("winrate", 0.0)
            max_sw      = rd.get("max_seq_win",  0)
            max_sl      = rd.get("max_seq_loss", 0)
            seq_w_at    = rd.get("seq_win_atual",  0)
            seq_l_at    = rd.get("seq_loss_atual", 0)
            seqs_win    = rd.get("sequencias_win",  [])
            seqs_loss   = rd.get("sequencias_loss", [])

            # Sequências de wins formatadas
            sw_txt = " | ".join(
                f"{s['tamanho']}W({s['inicio']})" for s in seqs_win[-5:]
            ) if seqs_win else "nenhuma"

            # Sequências de losses formatadas
            sl_txt = " | ".join(
                f"{s['tamanho']}L({s['inicio']})" for s in seqs_loss[-5:]
            ) if seqs_loss else "nenhuma"

            # Streak atual
            if seq_w_at >= 1:
                streak_txt = f"🔥 <b>{seq_w_at} wins seguidos agora</b>"
            elif seq_l_at >= 1:
                streak_txt = f"💀 <b>{seq_l_at} losses seguidos agora</b>"
            else:
                streak_txt = "—"

            # Últimos 8 resultados do histórico (hoje)
            historico_hoje = [
                r for r in dados.get("historico", [])
                if r.get("ts", "").startswith(hoje)
            ][-8:]
            linha_hist = ""
            for r in historico_hoje:
                em   = "✅" if r["tipo"] == "WIN" else "❌"
                hora = r["ts"][11:16]
                cat  = r.get("cat_label", "?")
                consec_w = r.get("wins_consecutivos",  0)
                consec_l = r.get("losses_consecutivos", 0)
                streak_r = f" 🔥{consec_w}W" if consec_w >= 2 else (f" 💀{consec_l}L" if consec_l >= 2 else "")
                linha_hist += f"  {em} {hora}  CAT{r.get('categoria','?')} {cat}{streak_r}\n"

            bot.send_message(message.chat.id,
                f"📋 <b>REGISTRO — HOJE {hoje[5:]}</b>\n"
                f"{'─'*24}\n"
                f"✅ Wins: <b>{wins_hoje}</b>  "
                f"❌ Losses: <b>{losses_hoje}</b>  "
                f"📊 <b>{wr_hoje}%</b>\n\n"
                f"🔥 Maior seq. WIN:  <b>{max_sw}W</b>\n"
                f"💀 Maior seq. LOSS: <b>{max_sl}L</b>\n"
                f"⚡ Agora: {streak_txt}\n\n"
                f"📈 Seq. wins hoje:  <code>{sw_txt}</code>\n"
                f"📉 Seq. losses hoje: <code>{sl_txt}</code>\n"
                f"{'─'*24}\n"
                f"<b>Últimos {len(historico_hoje)} sinais:</b>\n"
                f"{linha_hist if linha_hist else '  <i>sem sinais hoje</i>'}",
                parse_mode="HTML"
            )

        @bot.message_handler(commands=["stats"])
        def cmd_stats(message):
            if message.chat.id != cfg.chat_id: return
            bot.send_message(cfg.chat_id, self.stats.to_message(), parse_mode="HTML")

        @bot.message_handler(commands=["ab"])
        def cmd_ab(message):
            if message.chat.id != cfg.chat_id: return
            bot.send_message(cfg.chat_id, self.ab.build_report(), parse_mode="HTML")

        @bot.message_handler(commands=["banca"])
        def cmd_banca(message):
            if message.chat.id != cfg.chat_id: return
            bot.send_message(cfg.chat_id,
                f"💰 <b>Detalhes da Banca</b>\n\n"
                f"Saldo Atual: <b>R$ {self.gestor_banca.banca_atual:.2f}</b>\n"
                f"Nível: <b>{self.gestor_banca.nivel_atual}</b>/10\n"
                f"Próxima Aposta: <b>R$ {self.gestor_banca.get_valor_aposta():.2f}</b>",
                parse_mode="HTML")

        @bot.message_handler(commands=["regime"])
        def cmd_regime(message):
            if message.chat.id != cfg.chat_id: return
            r = self.regime
            hist = r._historico_regimes[-5:]
            hist_txt = ""
            if hist:
                linhas_h = [f"  {h['hora']} {h['de']} → {h['para']}" for h in reversed(hist)]
                hist_txt = "\n<b>Últimas transições:</b>\n" + "\n".join(linhas_h)
            bot.send_message(cfg.chat_id,
                f"🌊 <b>Regime Atual VP</b>\n\n"
                f"{r.linha_status()}\n"
                f"🏆 Dominante: {COLOR_LETTER_TO_EMOJI.get(r.dominante,'?') if r.dominante else '—'}\n"
                f"🎯 Score bônus: <b>{r.score_bonus():+d}</b>\n"
                f"📈 Score mínimo override: <b>{r.score_minimo_override(self.score_minimo_atual)}</b>"
                f"{hist_txt}",
                parse_mode="HTML")

        @bot.message_handler(commands=["autobet"])
        def cmd_autobet(message):
            if message.chat.id != cfg.chat_id: return
            if not self.autobet:
                bot.send_message(cfg.chat_id,
                    "⚠️ AutoBet não configurado. Defina <code>[autobet] ativo = true</code> no config.ini",
                    parse_mode="HTML")
                return
            bot.send_message(cfg.chat_id, self.autobet.status_line(), parse_mode="HTML")

        @bot.message_handler(commands=["resetbet"])
        def cmd_resetbet(message):
            if message.chat.id != cfg.chat_id: return
            if not self.autobet:
                bot.send_message(cfg.chat_id, "⚠️ AutoBet não ativo.", parse_mode="HTML")
                return
            self.autobet.reset_sessao()
            bot.send_message(cfg.chat_id,
                "🔄 <b>Sessão AutoBet reiniciada!</b>\n"
                f"Nível: 1 | PnL: R$0,00\n"
                f"Próxima aposta: R${cfg.autobet.aposta_base:.2f}",
                parse_mode="HTML")

        @bot.message_handler(commands=["resetscore"])
        def cmd_resetscore(message):
            if message.chat.id != cfg.chat_id: return
            resetados = 0
            for ks, rec in self.pattern_records.items():
                if rec.score_minimo_individual != SCORE_MIN_INICIAL:
                    rec.score_minimo_individual = SCORE_MIN_INICIAL
                    resetados += 1
            self._save_pattern_db()
            bot.send_message(cfg.chat_id,
                f"🔄 <b>Score mínimo individual resetado!</b>\n"
                f"📊 {resetados} padrões voltaram para <b>{SCORE_MIN_INICIAL}</b>\n"
                f"📏 Piso: {SCORE_MIN_FLOOR} | Teto: {SCORE_MIN_TETO}",
                parse_mode="HTML")

        @bot.message_handler(commands=["motor"])
        def cmd_motor(message):
            if message.chat.id != cfg.chat_id: return
            if not self.history_buffer:
                bot.send_message(cfg.chat_id,
                    "⚠️ Histórico ainda não carregado.", parse_mode="HTML")
                return
            resultado = _motor_decisao.analisar(self.history_buffer)
            bot.send_message(cfg.chat_id,
                _motor_decisao.build_telegram_msg(resultado), parse_mode="HTML")

        @bot.message_handler(commands=["padroes"])
        def cmd_padroes(message):
            if message.chat.id != cfg.chat_id: return
            CE   = {"V": "🔴", "P": "⚫"}
            listas = [
                ("A","padroes_lista_A_normal.json",      self.patterns_a),
                ("B","padroes_lista_B_top.json",   self.patterns_b),
                ("C","padroes_lista_C_elite.json", self.patterns_c),
                ("D","padroes_lista_D_origem.json",  self.patterns_d),
            ]
            msg = "📋 <b>PADRÕES VP ATIVOS</b> (tam. 5-6 | ≥90% | ≥11 testes)\n"
            for nome, arq, lista in listas:
                msg += f"\n<b>Lista {nome}</b> ({len(lista)} padrões):\n"
                for i, e in enumerate(lista[:15]):
                    p = " → ".join(CE.get(c, c) for c in e[0])
                    msg += f"  <code>{i+1}.</code> {p} → {CE.get(e[1], e[1])}\n"
                if len(lista) > 15:
                    msg += f"  <i>... e mais {len(lista)-15}</i>\n"
            bot.send_message(cfg.chat_id, msg, parse_mode="HTML")

        @bot.message_handler(commands=["learner"])
        def cmd_learner(message):
            if message.chat.id != cfg.chat_id: return
            msg = "\n\n".join([
                self.auto_learner_a.stats_summary(),
                self.auto_learner_b.stats_summary(),
                self.auto_learner_c.stats_summary(),
                self.auto_learner_d.stats_summary(),
            ])
            bot.send_message(cfg.chat_id, msg, parse_mode="HTML")

        @bot.message_handler(commands=["top10"])
        def cmd_top10(message):
            if message.chat.id != cfg.chat_id: return
            asyncio.run_coroutine_threadsafe(self._send_top10_padroes(), asyncio.get_event_loop())

        @bot.message_handler(commands=["relatorio"])
        def cmd_relatorio(message):
            if message.chat.id != cfg.chat_id: return
            asyncio.run_coroutine_threadsafe(self._send_relatorio_3min(), asyncio.get_event_loop())

        @bot.message_handler(commands=["simgale"])
        def cmd_simgale(message):
            if message.chat.id != cfg.chat_id: return
            bot.send_message(cfg.chat_id, _sim_gale.resumo(), parse_mode="HTML")

        @bot.message_handler(commands=["seca"])
        def cmd_seca(message):
            if message.chat.id != cfg.chat_id: return
            bot.send_message(cfg.chat_id, _mente_viva.resumo_rapido(), parse_mode="HTML")
        def cmd_posminera(message):
            if message.chat.id != cfg.chat_id: return
            partes = message.text.strip().split()
            modo   = partes[1].lower() if len(partes) > 1 else "ultimo"

            if modo == "historico" or modo == "hist":
                bot.send_message(cfg.chat_id,
                    _pos_mineracao.relatorio_historico(), parse_mode="HTML")
            elif modo == "status":
                if _pos_mineracao.monitorando:
                    sinais_feitos = _pos_mineracao.MAX_SINAIS - _pos_mineracao.sinais_restantes
                    bot.send_message(cfg.chat_id,
                        f"⏱️ <b>Monitoramento ativo</b>\n"
                        f"Sinais registrados: <b>{sinais_feitos}/{_pos_mineracao.MAX_SINAIS}</b>\n"
                        f"Restantes: <b>{_pos_mineracao.sinais_restantes}</b>",
                        parse_mode="HTML")
                else:
                    bot.send_message(cfg.chat_id,
                        "📊 <b>Pós-Mineração</b>: nenhum monitoramento ativo.\n"
                        "Use /minerar para iniciar.", parse_mode="HTML")
            else:
                # Padrão: último ciclo
                bot.send_message(cfg.chat_id,
                    _pos_mineracao.relatorio_ultimo(), parse_mode="HTML")

        @bot.message_handler(commands=["vermelho"])
        def cmd_vermelho(message):
            if message.chat.id != cfg.chat_id: return
            if not self.vermelho_integrador:
                bot.send_message(cfg.chat_id,
                    "⚠️ VermelhoEngine não carregado.", parse_mode="HTML")
                return
            bot.send_message(cfg.chat_id,
                self.vermelho_integrador.relatorio_completo(), parse_mode="HTML")

        @bot.message_handler(commands=["ve"])
        def cmd_ve_status(message):
            if message.chat.id != cfg.chat_id: return
            if not self.vermelho_integrador:
                bot.send_message(cfg.chat_id,
                    "⚠️ VermelhoEngine não carregado.", parse_mode="HTML")
                return
            resultado = self.vermelho_integrador.engine.analisar(self.history_buffer)
            bot.send_message(cfg.chat_id,
                self.vermelho_integrador.engine.build_telegram_msg(resultado),
                parse_mode="HTML")

        @bot.message_handler(commands=["cordom"])
        def cmd_cordom(message):
            if message.chat.id != cfg.chat_id: return
            asyncio.run_coroutine_threadsafe(self._send_cor_dominante_stats(), asyncio.get_event_loop())

        @bot.message_handler(commands=["minerador"])
        def cmd_minerador_status(message):
            if message.chat.id != cfg.chat_id: return
            nivel = self.minerador._nivel_atual
            melhor = self.minerador._melhor_nivel()
            stats_txt = "\n".join(
                f"  {label}: {s['wins']}/{s['total']} "
                f"({s['wins']/s['total']*100:.0f}%)" if s['total'] > 0
                else f"  {label}: sem dados"
                for label, s in self.minerador._nivel_stats.items()
            )
            proxima_min = max(0, int((self.minerador._ultima_mineracao + MINERADOR_INTERVALO_HORAS*3600 - time.time())/60))
            bot.send_message(cfg.chat_id,
                f"🔍 <b>Status do Minerador VP</b>\n\n"
                f"🎯 Nível atual (rodízio): <b>{nivel['label']}</b>\n"
                f"   ≥{nivel['ocorrencias']} ocorrências | ≥{nivel['winrate']*100:.0f}%\n\n"
                f"📊 Desempenho por nível:\n{stats_txt}\n\n"
                f"🏆 Nível mais eficaz: <b>{melhor}</b>\n"
                f"⏱️ Próxima mineração automática: <b>{proxima_min} min</b>\n\n"
                f"💡 Use /minerar para forçar agora\n"
                f"   /minerar 11 → força com nível 11\n"
                f"   /minerar 12 → força com nível 12\n"
                f"   /minerar 13 → força com nível 13",
                parse_mode="HTML")

        @bot.message_handler(commands=["rtminer"])
        def cmd_rtminer(message):
            """Mostra status e padrões ativos do minerador em tempo real."""
            CE = {"V": "🔴", "P": "⚫"}
            pats = self._rt_patterns
            ts   = self._rt_ultima_mine_ts or "ainda não rodou"
            buf_vp = [c for c in self.history_buffer if c in ("V","P")]

            if not pats:
                bot.send_message(message.chat.id,
                    f"🔄 <b>Minerador ao vivo</b>\n"
                    f"Ainda não minerou nenhum padrão.\n"
                    f"Buffer atual: {len(buf_vp)} rodadas VP\n"
                    f"Roda a cada {MINER_RT_A_CADA_RODADAS} rodadas.",
                    parse_mode="HTML")
                return

            linhas = ""
            for p in pats[:15]:
                try:
                    cores = "".join(CE.get(c,c) for c in p[0])
                    pred  = CE.get(p[1], p[1])
                    linhas += f"  {cores} → {pred}\n"
                except: pass

            bot.send_message(message.chat.id,
                f"🔄 <b>Minerador ao vivo</b>\n"
                f"{'─'*22}\n"
                f"🕐 Última mineração: <b>{ts}</b>\n"
                f"📊 Janela: <b>{len(buf_vp)}</b> rodadas VP\n"
                f"🎯 Padrões ativos: <b>{len(pats)}</b>\n"
                f"🔢 Total minerados: <b>{self._rt_total_minerados}</b>\n"
                f"⚙️ WR mínimo: <b>{MINER_RT_MIN_WR*100:.0f}%</b> | "
                f"Ocorrências mín: <b>{MINER_RT_MIN_OC}</b>\n"
                f"{'─'*22}\n"
                f"<b>Top 15 padrões ativos:</b>\n{linhas}"
                f"💡 <i>Gerados do histórico ao vivo — sem arquivo fixo</i>",
                parse_mode="HTML"
            )

        @bot.message_handler(commands=["minerar"])
        def cmd_minerar(message):
            if message.chat.id != cfg.chat_id: return

            # Verifica se já está rodando
            if self.minerador._rodando:
                bot.send_message(cfg.chat_id,
                    "⏳ <b>Minerador já está em execução</b>\n"
                    "Aguarde terminar antes de iniciar outro.",
                    parse_mode="HTML")
                return

            # Opção de nível via argumento: /minerar 11, /minerar 12, /minerar 13
            partes = message.text.strip().split()
            nivel_forçado = None
            if len(partes) > 1:
                try:
                    n = int(partes[1])
                    nivel_forçado = next(
                        (nv for nv in MINERADOR_NIVEIS if nv["ocorrencias"] == n), None)
                    if not nivel_forçado:
                        bot.send_message(cfg.chat_id,
                            f"⚠️ Nível <b>{n}</b> inválido. Use: /minerar 11, /minerar 12 ou /minerar 13",
                            parse_mode="HTML")
                        return
                except ValueError:
                    bot.send_message(cfg.chat_id,
                        "⚠️ Use: <code>/minerar</code> ou <code>/minerar 11</code>",
                        parse_mode="HTML")
                    return

            bot.send_message(cfg.chat_id,
                f"🔍 <b>Mineração manual iniciada!</b>\n"
                f"Nível: <b>{nivel_forçado['label'] if nivel_forçado else self.minerador._nivel_atual['label']}</b>\n"
                f"⏳ Coletando histórico...",
                parse_mode="HTML")

            # Força a mineração ignorando o timer de intervalo
            async def _forcar_mineracao():
                self.minerador._rodando = True
                nivel_exec = nivel_forçado if nivel_forçado else self.minerador._nivel_atual
                log.info(f"🔍 MINERAÇÃO MANUAL | nível={nivel_exec['label']}")
                try:
                    historico = await self.minerador._coletar_historico()
                    if len(historico) < 200:
                        await self._send_async("⚠️ <b>Mineração manual</b>: histórico insuficiente.")
                        return
                    resultados = self.minerador._minerar(historico, nivel_exec)
                    if resultados:
                        adicionados = await self.minerador._salvar(resultados)
                        self.patterns_a = self._load_patterns("padroes_lista_A_normal.json")
                        self.patterns_b = self._load_patterns("padroes_lista_B_top.json")
                        self.patterns_c = self._load_patterns("padroes_lista_C_elite.json")
                        self.patterns_d = self._load_patterns("padroes_lista_D_origem.json")
                        total_pads = (len(self.patterns_a) + len(self.patterns_b) +
                                      len(self.patterns_c) + len(self.patterns_d))
                        await self._send_async(
                            f"✅ <b>Mineração manual concluída!</b>\n"
                            f"{'─' * 20}\n"
                            f"🎯 Nível: <b>{nivel_exec['label']}</b>\n"
                            f"📏 Histórico: <b>{len(historico)}</b> rodadas VP\n"
                            f"🆕 Novos padrões: <b>{adicionados}</b>\n"
                            f"📊 Total ativo: <b>{total_pads}</b>\n"
                            f"🅰️ A={len(self.patterns_a)} | 🅱️ B={len(self.patterns_b)} | "
                            f"🏅 C={len(self.patterns_c)} | 📂 D={len(self.patterns_d)}\n\n"
                            f"⏱️ Monitorando próximos <b>4 sinais</b> pós-mineração..."
                        )
                        # ── Inicia rastreamento dos 6 próximos sinais ──
                        _pos_mineracao.iniciar_ciclo(nivel_exec["label"], adicionados)
                    else:
                        await self._send_async(
                            f"🔍 <b>Mineração manual concluída</b>\n"
                            f"Nível: <b>{nivel_exec['label']}</b> — nenhum padrão novo encontrado."
                        )
                    # Avança rodízio automático após mineração manual
                    self.minerador._avancar_nivel()
                    self.minerador._ultima_mineracao = time.time()
                except Exception as e:
                    log.error(f"Mineração manual erro: {e}")
                    await self._send_async(f"❌ <b>Mineração manual falhou:</b> {e}")
                finally:
                    self.minerador._rodando = False

            asyncio.run_coroutine_threadsafe(
                _forcar_mineracao(), asyncio.get_event_loop()
            )

        @bot.message_handler(commands=["kelly"])
        def cmd_kelly(message):
            if message.chat.id != cfg.chat_id: return
            # Calcula Kelly para o melhor padrão ativo
            confiaveis = {ks: rec for ks, rec in self.pattern_records.items() if rec.total >= 5}
            if not confiaveis:
                bot.send_message(cfg.chat_id,
                    "📐 <b>Kelly Criterion</b>: aguardando dados (mín. 5 sinais).",
                    parse_mode="HTML")
                return
            melhor_ks  = max(confiaveis, key=lambda k: confiaveis[k].accuracy)
            melhor_rec = confiaveis[melhor_ks]
            r = _kelly.calcular(melhor_rec.wins, melhor_rec.total,
                                payout=2.0, banca=self.gestor_banca.banca_atual)
            bot.send_message(cfg.chat_id,
                f"📐 <b>Kelly Criterion</b>\n\n"
                f"Padrão mais forte ({melhor_rec.accuracy:.0f}% | {melhor_rec.total} sinais)\n"
                f"{r['linha']}\n\n"
                f"{_kelly.resumo()}",
                parse_mode="HTML")

        @bot.message_handler(commands=["ev"])
        def cmd_ev(message):
            if message.chat.id != cfg.chat_id: return
            confiaveis = {ks: rec for ks, rec in self.pattern_records.items() if rec.total >= 3}
            if not confiaveis:
                bot.send_message(cfg.chat_id,
                    "💹 <b>Expected Value</b>: aguardando dados (mín. 3 sinais).",
                    parse_mode="HTML")
                return
            linhas = []
            top5 = sorted(confiaveis.items(), key=lambda x: x[1].accuracy, reverse=True)[:5]
            for ks, rec in top5:
                nome = self.pattern_names._map.get(ks, "?")
                r = _ev_calc.calcular(rec.wins, rec.total, payout=2.0,
                                      aposta=self.gestor_banca.get_valor_aposta(),
                                      pattern_nome=nome)
                linhas.append(f"[{nome}] {rec.accuracy:.0f}% → {r['linha']}")
            bot.send_message(cfg.chat_id,
                f"💹 <b>Expected Value — Top 5 Padrões</b>\n\n"
                + "\n".join(linhas) +
                f"\n\n{_ev_calc.resumo()}",
                parse_mode="HTML")

        @bot.message_handler(commands=["f1"])
        def cmd_f1(message):
            if message.chat.id != cfg.chat_id: return
            bot.send_message(cfg.chat_id, _confusion.resumo(), parse_mode="HTML")

        @bot.message_handler(commands=["bootstrap"])
        def cmd_bootstrap(message):
            if message.chat.id != cfg.chat_id: return
            confiaveis = {ks: rec for ks, rec in self.pattern_records.items() if rec.total >= 5}
            if not confiaveis:
                bot.send_message(cfg.chat_id,
                    "🔬 <b>Bootstrap</b>: aguardando dados (mín. 5 sinais).",
                    parse_mode="HTML")
                return
            linhas = []
            top5 = sorted(confiaveis.items(), key=lambda x: x[1].accuracy, reverse=True)[:5]
            for ks, rec in top5:
                nome = self.pattern_names._map.get(ks, "?")
                r = _bootstrap.validar(rec.wins, rec.total, limiar=0.90, pattern_nome=nome)
                linhas.append(f"[{nome}] {rec.accuracy:.0f}% ({rec.total} sinais)\n  {r['linha']}")
            bot.send_message(cfg.chat_id,
                f"🔬 <b>Bootstrap — Validade dos Top 5 Padrões</b>\n\n"
                + "\n\n".join(linhas) +
                f"\n\n{_bootstrap.resumo()}",
                parse_mode="HTML")

        @bot.message_handler(commands=["brancostats"])
        def cmd_brancostats(message):
            if message.chat.id != cfg.chat_id: return
            bot.send_message(cfg.chat_id, _branco_stats.resumo(), parse_mode="HTML")

        @bot.message_handler(commands=["branco"])
        def cmd_branco(message):
            if message.chat.id != cfg.chat_id: return
            alerta = _branco_detector.checar_alerta()
            resumo = _branco_detector.resumo()
            top5_txt = ""

        @bot.message_handler(commands=["brancohist"])
        def cmd_brancohist(message):
            if message.chat.id != cfg.chat_id: return
            bot.send_message(cfg.chat_id, _branco_hist.resumo(), parse_mode="HTML")
            for i, p in enumerate(_branco_detector._padroes[:5], 1):
                top5_txt += (
                    f"  {i}. <b>{p['formula']}</b> {p['condicao']} | "
                    f"{p['taxa_pct']} ({p['acertos']}/{p['total']} brancos) "
                    f"janela={p['janela']}\n"
                )
            alerta_txt = ""
            if alerta["score"] > 0:
                alerta_txt = f"\n⚠️ <b>ALERTA ATIVO!</b>\n{alerta['linha']}\n"
            bot.send_message(cfg.chat_id,
                f"⚪ <b>BrancoDetector</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"{resumo}\n\n"
                f"🏆 <b>Top 5 Fórmulas:</b>\n{top5_txt}"
                f"{alerta_txt}"
                f"━━━━━━━━━━━━━━━━━━",
                parse_mode="HTML")

        @bot.message_handler(commands=["pares"])
        def cmd_pares(message):
            if message.chat.id != cfg.chat_id: return
            if not _NUMERO_STATS_DISPONIVEL:
                bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
                return
            bot.send_message(cfg.chat_id, _grupo_seco.resumo_top5(), parse_mode="HTML")

        @bot.message_handler(commands=["par"])
        def cmd_par(message):
            if message.chat.id != cfg.chat_id: return
            if not _NUMERO_STATS_DISPONIVEL:
                bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
                return
            try:
                partes = message.text.split()
                a = int(partes[1])
                b = int(partes[2]) if len(partes) > 2 else a
                if not (0 <= a <= 14 and 0 <= b <= 14):
                    raise ValueError
                bot.send_message(cfg.chat_id,
                    _grupo_seco.mensagem_consulta_par(a, b), parse_mode="HTML")
            except (IndexError, ValueError):
                bot.send_message(cfg.chat_id,
                    "⚠️ Use: <code>/par 7 10</code> (dois números) ou <code>/par 7</code> (um número)\n"
                    "Números válidos: 0 a 14",
                    parse_mode="HTML")
            if message.chat.id != cfg.chat_id: return
            if not _NUMERO_STATS_DISPONIVEL:
                bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
                return
            bot.send_message(cfg.chat_id,
                _numero_stats.resumo_top5_secos(), parse_mode="HTML")

        @bot.message_handler(commands=["numero"])
        def cmd_numero(message):
            if message.chat.id != cfg.chat_id: return
            if not _NUMERO_STATS_DISPONIVEL:
                bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
                return
            try:
                n = int(message.text.split()[1])
                if n < 0 or n > 14:
                    raise ValueError
                bot.send_message(cfg.chat_id,
                    _numero_stats.resumo_numero(n), parse_mode="HTML")
            except (IndexError, ValueError):
                bot.send_message(cfg.chat_id,
                    "⚠️ Use: <code>/numero 0</code> a <code>/numero 14</code>",
                    parse_mode="HTML")

        @bot.message_handler(commands=["numerostodos"])
        def cmd_numeros_todos(message):
            if message.chat.id != cfg.chat_id: return
            if not _NUMERO_STATS_DISPONIVEL:
                bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
                return
            bot.send_message(cfg.chat_id,
                _numero_stats.resumo_completo(), parse_mode="HTML")

        @bot.message_handler(commands=["frequentes"])
        def cmd_frequentes(message):
            if message.chat.id != cfg.chat_id: return
            if not _NUMERO_STATS_DISPONIVEL:
                bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
                return
            bot.send_message(cfg.chat_id,
                _numero_stats.resumo_frequentes(), parse_mode="HTML")

        @bot.message_handler(commands=["horafavorita"])
        def cmd_horafavorita(message):
            if message.chat.id != cfg.chat_id: return
            hora_atual = datetime.now().strftime("%H")
            resumo = _numero_hora.resumo_geral()
            alerta = _numero_hora.linha_alerta_hora_atual()
            # Monta tabela completa dos top números por hora favorita
            linhas = []
            for n in range(15):
                hf = _numero_hora.hora_favorita(n)
                if hf["hora"] is None:
                    continue
                emoji = "🔥" if hf["fator"] >= 2.0 else ("⭐" if hf["fator"] >= 1.5 else "")
                linhas.append(
                    f"  N{n:2d}  hora pico: <b>{hf['hora']}h</b>  "
                    f"fator: <b>{hf['fator']}×</b>  "
                    f"({hf['contagem']}/{hf['total']}) {emoji}"
                )
            tabela = "\n".join(linhas) if linhas else "<i>Coletando dados...</i>"
            alerta_txt = f"\n{alerta}\n" if alerta else ""
            bot.send_message(cfg.chat_id,
                f"🕐 <b>Hora Favorita por Número</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"{resumo}\n\n"
                f"📋 <b>Todos os números:</b>\n{tabela}"
                f"{alerta_txt}"
                f"\n━━━━━━━━━━━━━━━━━━",
                parse_mode="HTML")

        @bot.message_handler(commands=["numero"])
        def cmd_numero(message):
            if message.chat.id != cfg.chat_id: return
            # /numero 10 → detalhe do número 10
            try:
                partes = message.text.strip().split()
                n = int(partes[1]) if len(partes) > 1 else -1
                if n < 0 or n > 14:
                    raise ValueError
            except Exception:
                bot.send_message(cfg.chat_id,
                    "⚠️ Use: <code>/numero 0</code> a <code>/numero 14</code>",
                    parse_mode="HTML")
                return
            bot.send_message(cfg.chat_id,
                _numero_hora.resumo_numero(n),
                parse_mode="HTML")


        def cmd_iniciar(message):
            if message.chat.id != cfg.chat_id: return
            self.running = True; self.protected = False; self.stats = Stats()
            bot.send_message(cfg.chat_id,
                "▶️ <b>Bot VP iniciado!</b>\n🔴 Vermelho + ⚫ Preto", parse_mode="HTML")

        @bot.message_handler(commands=["parar"])
        def cmd_parar(message):
            if message.chat.id != cfg.chat_id: return
            self.running = False
            bot.send_message(cfg.chat_id,
                "⏸️ <b>Bot pausado.</b> Use /iniciar para retomar.", parse_mode="HTML")

        @bot.callback_query_handler(func=lambda c: True)
        def handle_callback(call):
            if call.message.chat.id != cfg.chat_id: return
            if call.data == "stats":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, self.stats.to_message(), parse_mode="HTML")
            elif call.data == "ab":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, self.ab.build_report(), parse_mode="HTML")
            elif call.data == "banca":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id,
                    f"💰 <b>Banca</b>\nSaldo: <b>R$ {self.gestor_banca.banca_atual:.2f}</b>\n"
                    f"Nível: <b>{self.gestor_banca.nivel_atual}</b>/10\n"
                    f"Aposta: <b>R$ {self.gestor_banca.get_valor_aposta():.2f}</b>",
                    parse_mode="HTML")
            elif call.data == "autobet":
                bot.answer_callback_query(call.id)
                if not self.autobet:
                    bot.send_message(cfg.chat_id, "⚠️ AutoBet não ativo.", parse_mode="HTML")
                    return
                bot.send_message(cfg.chat_id, self.autobet.status_line(), parse_mode="HTML")
            elif call.data == "motor":
                bot.answer_callback_query(call.id)
                if not self.history_buffer:
                    bot.send_message(cfg.chat_id, "⚠️ Histórico não carregado.", parse_mode="HTML")
                    return
                resultado = _motor_decisao.analisar(self.history_buffer)
                bot.send_message(cfg.chat_id,
                    _motor_decisao.build_telegram_msg(resultado), parse_mode="HTML")
            elif call.data == "regime":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, self.regime.linha_status(), parse_mode="HTML")
            elif call.data == "minerar":
                bot.answer_callback_query(call.id, "⛏️ Iniciando mineração...")
                if self.minerador._rodando:
                    bot.send_message(cfg.chat_id,
                        "⏳ <b>Minerador já está em execução.</b>\nAguarde terminar.",
                        parse_mode="HTML")
                else:
                    bot.send_message(cfg.chat_id,
                        f"⛏️ <b>Mineração manual iniciada!</b>\n"
                        f"Nível: <b>{self.minerador._nivel_atual['label']}</b>\n"
                        f"⏳ Coletando histórico...",
                        parse_mode="HTML")
                    async def _minar_callback():
                        self.minerador._rodando = True
                        nivel_exec = self.minerador._nivel_atual
                        try:
                            historico = await self.minerador._coletar_historico()
                            if len(historico) < 200:
                                await self._send_async("⚠️ Histórico insuficiente para minerar.")
                                return
                            resultados = self.minerador._minerar(historico, nivel_exec)
                            if resultados:
                                adicionados = await self.minerador._salvar(resultados)
                                self.patterns_a = self._load_patterns("padroes_lista_A_normal.json")
                                self.patterns_b = self._load_patterns("padroes_lista_B_top.json")
                                self.patterns_c = self._load_patterns("padroes_lista_C_elite.json")
                                self.patterns_d = self._load_patterns("padroes_lista_D_origem.json")
                                total_pads = (len(self.patterns_a) + len(self.patterns_b) +
                                              len(self.patterns_c) + len(self.patterns_d))
                                await self._send_async(
                                    f"✅ <b>Mineração concluída!</b>\n"
                                    f"🆕 Novos: <b>{adicionados}</b>  │  Total: <b>{total_pads}</b>"
                                )
                            else:
                                await self._send_async("🔍 Mineração concluída — nenhum padrão novo.")
                            self.minerador._avancar_nivel()
                            self.minerador._ultima_mineracao = time.time()
                        except Exception as e:
                            await self._send_async(f"❌ Mineração falhou: {e}")
                        finally:
                            self.minerador._rodando = False
                    asyncio.run_coroutine_threadsafe(
                        _minar_callback(), asyncio.get_event_loop()
                    )
            elif call.data == "kelly":
                bot.answer_callback_query(call.id)
                confiaveis = {ks: rec for ks, rec in self.pattern_records.items() if rec.total >= 5}
                if not confiaveis:
                    bot.send_message(cfg.chat_id, "📐 Kelly: aguardando dados (mín. 5 sinais).", parse_mode="HTML")
                else:
                    melhor_ks  = max(confiaveis, key=lambda k: confiaveis[k].accuracy)
                    melhor_rec = confiaveis[melhor_ks]
                    r = _kelly.calcular(melhor_rec.wins, melhor_rec.total,
                                        payout=2.0, banca=self.gestor_banca.banca_atual)
                    bot.send_message(cfg.chat_id,
                        f"📐 <b>Kelly Criterion</b>\n\n{r['linha']}\n\n{_kelly.resumo()}",
                        parse_mode="HTML")
            elif call.data == "ev":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, _ev_calc.resumo(), parse_mode="HTML")
            elif call.data == "f1":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, _confusion.resumo(), parse_mode="HTML")
            elif call.data == "bootstrap":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, _bootstrap.resumo(), parse_mode="HTML")
            elif call.data == "brancostats":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, _branco_stats.resumo(), parse_mode="HTML")
            elif call.data == "branco":
                bot.answer_callback_query(call.id)
                alerta = _branco_detector.checar_alerta()
                alerta_txt = f"\n⚠️ <b>ALERTA ATIVO!</b>\n{alerta['linha']}" if alerta["score"] >= 20 else "\n✅ Nenhum alerta ativo agora."
                bot.send_message(cfg.chat_id,
                    f"{_branco_detector.resumo()}{alerta_txt}", parse_mode="HTML")
            elif call.data == "brancohist":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, _branco_hist.resumo(), parse_mode="HTML")
            elif call.data == "numeros":
                bot.answer_callback_query(call.id)
                if _NUMERO_STATS_DISPONIVEL:
                    bot.send_message(cfg.chat_id,
                        _numero_stats.resumo_top5_secos(), parse_mode="HTML")
                else:
                    bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
            elif call.data == "frequentes":
                bot.answer_callback_query(call.id)
                if _NUMERO_STATS_DISPONIVEL:
                    bot.send_message(cfg.chat_id,
                        _numero_stats.resumo_frequentes(), parse_mode="HTML")
                else:
                    bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
            elif call.data == "horafavorita":
                bot.answer_callback_query(call.id)
                resumo = _numero_hora.resumo_geral()
                alerta = _numero_hora.linha_alerta_hora_atual()
                alerta_txt = f"\n{alerta}" if alerta else ""
                bot.send_message(cfg.chat_id,
                    f"{resumo}{alerta_txt}", parse_mode="HTML")
            elif call.data == "iniciar":
                self.running = True; self.protected = False; self.stats = Stats()
                bot.answer_callback_query(call.id, "▶️ Bot VP iniciado!")
                bot.send_message(cfg.chat_id, "▶️ <b>Bot VP iniciado!</b>", parse_mode="HTML")
            elif call.data == "parar":
                self.running = False
                bot.answer_callback_query(call.id, "⏸️ Bot pausado!")
                bot.send_message(cfg.chat_id, "⏸️ <b>Bot pausado.</b>", parse_mode="HTML")
            elif call.data == "padroes":
                bot.answer_callback_query(call.id)
                CE = {"V": "🔴", "P": "⚫"}
                listas = [
                    ("A", self.patterns_a), ("B", self.patterns_b),
                    ("C", self.patterns_c), ("D", self.patterns_d),
                ]
                msg = "📋 <b>Padrões VP ativos</b>\n"
                for nome, lista in listas:
                    msg += f"\n<b>Lista {nome}</b> ({len(lista)}):\n"
                    for i, e in enumerate(lista[:8]):
                        p = "".join(CE.get(c, c) for c in e[0])
                        msg += f"  {i+1}. {p}→{CE.get(e[1],e[1])}\n"
                    if len(lista) > 8:
                        msg += f"  <i>+{len(lista)-8} mais</i>\n"
                bot.send_message(cfg.chat_id, msg, parse_mode="HTML")
            elif call.data == "top10":
                bot.answer_callback_query(call.id)
                asyncio.run_coroutine_threadsafe(
                    self._send_top10_padroes(), asyncio.get_event_loop())
            elif call.data == "posminera":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id,
                    _pos_mineracao.relatorio_ultimo(), parse_mode="HTML")
            elif call.data == "learner":
                bot.answer_callback_query(call.id)
                msg = "\n\n".join([
                    self.auto_learner_a.stats_summary(),
                    self.auto_learner_b.stats_summary(),
                    self.auto_learner_c.stats_summary(),
                    self.auto_learner_d.stats_summary(),
                ])
                bot.send_message(cfg.chat_id, msg, parse_mode="HTML")
            elif call.data == "minerador_status":
                bot.answer_callback_query(call.id)
                nivel  = self.minerador._nivel_atual
                melhor = self.minerador._melhor_nivel()
                proxima_min = max(0, int((self.minerador._ultima_mineracao
                                          + MINERADOR_INTERVALO_HORAS*3600
                                          - time.time()) / 60))
                bot.send_message(cfg.chat_id,
                    f"🔍 <b>Minerador VP</b>\n"
                    f"Nível atual: <b>{nivel['label']}</b>\n"
                    f"Melhor: <b>{melhor}</b>\n"
                    f"Próxima auto: <b>{proxima_min} min</b>\n"
                    f"Em execução: <b>{'Sim' if self.minerador._rodando else 'Não'}</b>",
                    parse_mode="HTML")
            elif call.data == "pares":
                bot.answer_callback_query(call.id)
                if _NUMERO_STATS_DISPONIVEL:
                    bot.send_message(cfg.chat_id,
                        _grupo_seco.resumo_top5(), parse_mode="HTML")
                else:
                    bot.send_message(cfg.chat_id, "⚠️ numero_stats.py não encontrado.", parse_mode="HTML")
            elif call.data == "resetscore":
                bot.answer_callback_query(call.id, "🔄 Resetando scores...")
                resetados = 0
                for rec in self.pattern_records.values():
                    if rec.score_minimo_individual != SCORE_MIN_INICIAL:
                        rec.score_minimo_individual = SCORE_MIN_INICIAL
                        resetados += 1
                self._save_pattern_db()
                bot.send_message(cfg.chat_id,
                    f"🔄 <b>Score mínimo resetado!</b>\n"
                    f"{resetados} padrões voltaram para <b>{SCORE_MIN_INICIAL}</b>",
                    parse_mode="HTML")
            elif call.data == "relatorio":
                bot.answer_callback_query(call.id)
                asyncio.run_coroutine_threadsafe(
                    self._send_relatorio_3min(), asyncio.get_event_loop())
            elif call.data == "simgale":
                bot.answer_callback_query(call.id)
                bot.send_message(cfg.chat_id, _sim_gale.resumo(), parse_mode="HTML")

    def _start_polling(self) -> None:
        import threading
        # Limpa webhook e updates pendentes — resolve erro 409 no reinício
        try:
            self.bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            log.warning(f"delete_webhook: {e}")

        def polling_loop():
            while True:
                try:
                    self.bot.infinity_polling(timeout=60, long_polling_timeout=55,
                                               allowed_updates=['message', 'callback_query'])
                except Exception as e:
                    err = str(e)
                    if "409" in err:
                        log.warning("Polling 409: aguardando 15s para outro processo liberar...")
                        time.sleep(15)
                    elif "ReadTimeout" in err or "read timeout" in err.lower() or "timed out" in err.lower():
                        # Timeout de rede é normal — reconecta silenciosamente (sem log)
                        time.sleep(2)
                    else:
                        log.warning(f"Polling caiu: {e}")
                        time.sleep(5)
        threading.Thread(target=polling_loop, daemon=True).start()

    def _send(self, text: str, markup=None) -> Optional[int]:
        try:
            future = self._tg_executor.submit(
                self.bot.send_message, self.cfg.chat_id, text,
                **{"reply_markup": markup, "parse_mode": "HTML"})
            return future.result(timeout=5).message_id
        except Exception as e:
            log.error(f"_send erro: {e}")
            return None

    def _delete(self, msg_id: Optional[int]) -> None:
        if msg_id:
            try:
                self._tg_executor.submit(self.bot.delete_message, self.cfg.chat_id, msg_id)
            except Exception:
                pass

    def _fire(self, coro) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # fallback se chamado fora do loop
            asyncio.run_coroutine_threadsafe(coro, asyncio.get_event_loop())
        except Exception as e:
            log.error(f"_fire erro: {e}")

    # ══════════════════════════════════════════════════════════════
    # MINERADOR EM TEMPO REAL
    # ══════════════════════════════════════════════════════════════

    def _minerar_tempo_real(self) -> None:
        """
        Minera padrões diretamente do history_buffer (histórico ao vivo).
        Roda a cada MINER_RT_A_CADA_RODADAS rodadas.
        Resultado fica em self._rt_patterns — totalmente em memória.
        NÃO usa arquivo JSON como intermediário.

        Lógica:
          1. Pega as últimas MINER_RT_JANELA rodadas VP do buffer
          2. Analisa todas as sequências de 5 e 6 cores
          3. Calcula WR de cada sequência → próxima cor
          4. Filtra: WR >= MINER_RT_MIN_WR e ocorrências >= MINER_RT_MIN_OC
          5. Ordena por WR desc, pega os top MINER_RT_MAX_PADROES
          6. Atualiza self._rt_patterns e também os patterns_c/b/a do bot
        """
        if not MINER_RT_ATIVO:
            return
        if not self.history_buffer:
            return

        # Usa as últimas JANELA rodadas VP (ignora branco)
        buf_vp = [c for c in self.history_buffer if c in ("V", "P")]
        buf = buf_vp[-MINER_RT_JANELA:] if len(buf_vp) > MINER_RT_JANELA else buf_vp

        if len(buf) < 50:
            return  # poucos dados

        # Minera sequências
        contagem: dict = {}
        for tam in MINER_RT_TAMANHOS:
            for i in range(len(buf) - tam):
                seq      = tuple(buf[i:i + tam])
                proximo  = buf[i + tam]
                chave    = (seq, proximo)
                contagem[chave] = contagem.get(chave, 0) + 1

        # Calcula WR por padrão
        padroes_unicos = set(k[0] for k in contagem)
        candidatos = []
        for padrao in padroes_unicos:
            tv = contagem.get((padrao, "V"), 0)
            tp = contagem.get((padrao, "P"), 0)
            total = tv + tp
            if total < MINER_RT_MIN_OC:
                continue
            melhor_pred = "V" if tv >= tp else "P"
            wins = max(tv, tp)
            wr   = wins / total
            if wr >= MINER_RT_MIN_WR:
                candidatos.append({
                    "pat":   list(padrao),
                    "pred":  melhor_pred,
                    "wr":    wr,
                    "wins":  wins,
                    "total": total,
                })

        # Ordena por WR desc, depois por total desc
        candidatos.sort(key=lambda x: (-x["wr"], -x["total"]))
        top = candidatos[:MINER_RT_MAX_PADROES]

        if not top:
            log.debug("🔄 Minerador RT: nenhum padrão novo neste ciclo")
            return

        # Converte para formato [[pat], pred]
        self._rt_patterns = [[c["pat"], c["pred"]] for c in top]
        self._rt_total_minerados += len(top)
        self._rt_ultima_mine_ts = datetime.now().strftime("%H:%M:%S")

        # ── Atualiza as listas ativas do bot em memória ──────────
        # Os padrões RT ficam na lista C (elite) para ter prioridade
        # Preserva os padrões fixos dos arquivos JSON e adiciona os RT
        padrao_fixo_c = BlazeBot._load_patterns("padroes_lista_C_elite.json")
        padrao_fixo_b = BlazeBot._load_patterns("padroes_lista_B_top.json")
        padrao_fixo_a = BlazeBot._load_patterns("padroes_lista_A_normal.json")

        # Converte RT para conjunto para deduplicar
        rt_set = {(tuple(p[0]), p[1]) for p in self._rt_patterns}
        fixo_set_c = {(tuple(p[0]), p[1]) for p in padrao_fixo_c}
        fixo_set_b = {(tuple(p[0]), p[1]) for p in padrao_fixo_b}
        fixo_set_a = {(tuple(p[0]), p[1]) for p in padrao_fixo_a}

        # Padrões RT que não estão nos fixos → são novos descobertos ao vivo
        rt_novos = [p for p in self._rt_patterns
                    if (tuple(p[0]), p[1]) not in fixo_set_c
                    and (tuple(p[0]), p[1]) not in fixo_set_b
                    and (tuple(p[0]), p[1]) not in fixo_set_a]

        # Lista C = fixos C + novos RT (ao vivo têm prioridade máxima)
        self.patterns_c = self._rt_patterns + [
            p for p in padrao_fixo_c
            if (tuple(p[0]), p[1]) not in rt_set
        ]
        self.patterns_b = padrao_fixo_b
        self.patterns_a = padrao_fixo_a

        novos_count = len(rt_novos)
        log.info(
            f"🔄 Minerador RT | {len(top)} padrões ativos | "
            f"{novos_count} novos ao vivo | "
            f"WR topo={top[0]['wr']*100:.1f}% | "
            f"janela={len(buf)} rodadas | {self._rt_ultima_mine_ts}"
        )

        # Notifica no Telegram quando encontra padrões novos (só se relevante)
        if novos_count > 0:
            CE = {"V": "🔴", "P": "⚫"}
            top3 = rt_novos[:3]
            linhas = ""
            for c in [next(x for x in top if x["pat"] == p[0] and x["pred"] == p[1])
                      for p in top3]:
                cores = "".join(CE.get(x, x) for x in c["pat"])
                pred  = CE.get(c["pred"], c["pred"])
                linhas += f"  {cores} → {pred}  {c['wr']*100:.0f}% ({c['wins']}W/{c['total']-c['wins']}L)\n"

            self._fire(self._send_async(
                f"🔄 <b>Minerador ao vivo</b> — {novos_count} padrão(ões) novo(s)\n"
                f"{'─'*20}\n"
                f"📊 Janela: <b>{len(buf)}</b> rodadas | "
                f"Ativos: <b>{len(top)}</b> padrões\n"
                f"🕐 {self._rt_ultima_mine_ts}\n"
                f"{linhas}"
                f"💡 <i>Criados do histórico ao vivo — sem arquivo fixo</i>"
            ))

    # ══════════════════════════════════════════════════════════════
    # SISTEMA DE 3 CATEGORIAS
    # ══════════════════════════════════════════════════════════════

    def _cat_emoji(self, cat: int) -> str:
        return CAT_EMOJIS.get(cat, "⬜")

    def _cat_label(self, cat: int) -> str:
        return CAT_LABELS.get(cat, "?")

    def _atualizar_cat(self, win: bool) -> None:
        """
        Regra simples baseada em resultado:
          WIN  → volta para CAT1, zera losses
          LOSS → sobe 1 categoria (1→2→3), máximo CAT3
        """
        cat_antes = self._cat_atual
        if win:
            self._cat_atual = 1
            self._cat_losses_seguidos = 0
            self._cat_motivo = f"WIN na CAT{cat_antes} → volta CAT1"
        else:
            self._cat_losses_seguidos += 1
            nova_cat = min(self._cat_atual + 1, 3)
            self._cat_atual = nova_cat
            self._cat_motivo = (
                f"LOSS na CAT{cat_antes} → sobe para CAT{nova_cat}"
            )

        em = self._cat_emoji(self._cat_atual)
        log.info(
            f"📊 CAT | {'WIN ✅' if win else 'LOSS ❌'} "
            f"CAT{cat_antes} → {em} CAT{self._cat_atual} | "
            f"{self._cat_losses_seguidos} losses seguidos"
        )

        # Avisa no Telegram quando sobe de categoria
        if not win:
            lbl = self._cat_label(self._cat_atual)
            em  = self._cat_emoji(self._cat_atual)
            self._fire(self._send_async(
                f"{em} <b>CATEGORIA {lbl}</b>\n"
                f"{'─' * 20}\n"
                f"Loss anterior moveu para <b>CAT{self._cat_atual}</b>\n"
                f"📊 {self._cat_losses_seguidos} loss(es) consecutivo(s)\n"
                f"💡 WIN em qualquer cat → volta CAT1 automaticamente"
            ))

    # ══════════════════════════════════════════════════════════════
    # REGISTRO JSON DE LOSSES / WINS
    # ══════════════════════════════════════════════════════════════
    def _registrar_resultado_json(self, win: bool) -> None:
        """
        Registra TODOS os resultados (wins e losses) em registro_resultados.json.

        Estrutura do JSON:
        {
          "historico": [                    ← lista cronológica de todos os sinais
            {
              "ts":                "2026-03-22 14:32:10",
              "tipo":              "WIN" | "LOSS",
              "categoria":         1 | 2 | 3,
              "cat_label":         "PRIMEIRA" | "SEGUNDA" | "TERCEIRA",
              "padrao":            "['V','P','V','P','V','P']",
              "predicao":          "P",
              "regime":            "chaotic" | "trending" | "alternating",
              "hora":              14,
              "wins_consecutivos": 3,        ← streak de wins no momento
              "losses_consecutivos": 0,      ← streak de losses no momento
              "wins_hoje":         8,
              "losses_hoje":       2,
              "banca":             2480.30
            }, ...
          ],
          "sequencias": {                   ← registro de todas as sequências
            "wins": [                       ← sequências de wins seguidos
              {"tamanho": 5, "inicio": "14:10", "fim": "14:35", "data": "2026-03-22"},
              ...
            ],
            "losses": [                     ← sequências de losses seguidos (>=2)
              {"tamanho": 3, "inicio": "12:06", "fim": "12:09", "data": "2026-03-22"},
              ...
            ]
          },
          "resumo_diario": {
            "2026-03-22": {
              "wins": 12, "losses": 4,
              "winrate": 75.0,
              "max_seq_win": 5,
              "max_seq_loss": 3,
              "sequencias_win":  [3, 5, 2],   ← todas as seq de win do dia
              "sequencias_loss": [2, 3],       ← todas as seq de loss do dia
              "seq_win_atual": 0,              ← streak em andamento
              "seq_loss_atual": 0
            }
          }
        }
        """
        import json as _json

        agora    = datetime.now()
        hoje_str = agora.strftime("%Y-%m-%d")
        hora_str = agora.strftime("%H:%M:%S")
        hora_int = agora.hour

        # ── Monta o registro do sinal ─────────────────────────────
        registro = {
            "ts":                agora.strftime("%Y-%m-%d %H:%M:%S"),
            "tipo":              "WIN" if win else "LOSS",
            "categoria":         self._cat_atual,
            "cat_label":         self._cat_label(self._cat_atual),
            "padrao":            str(self.prev_pattern)    if self.prev_pattern    else "—",
            "predicao":          str(self.prev_prediction) if self.prev_prediction else "—",
            "regime":            self.regime._estado,
            "hora":              hora_int,
            "wins_consecutivos": self.stats.consecutive_wins,
            "losses_consecutivos": self.stats.consecutive_losses,
            "wins_hoje":         self.stats.wins_hoje,
            "losses_hoje":       self.stats.losses_hoje,
            "banca":             round(self.gestor_banca.banca_atual, 2),
        }

        # ── Carrega JSON existente ────────────────────────────────
        try:
            with open(LOSS_JSON_FILE, "r", encoding="utf-8") as _f:
                dados = _json.load(_f)
        except Exception:
            dados = {
                "historico":    [],
                "sequencias":   {"wins": [], "losses": []},
                "resumo_diario": {}
            }

        # Garante estrutura mínima
        dados.setdefault("historico",     [])
        dados.setdefault("sequencias",    {"wins": [], "losses": []})
        dados.setdefault("resumo_diario", {})
        dados["sequencias"].setdefault("wins",   [])
        dados["sequencias"].setdefault("losses", [])

        # ── Adiciona ao histórico ─────────────────────────────────
        dados["historico"].append(registro)

        # ── Atualiza resumo diário ────────────────────────────────
        if hoje_str not in dados["resumo_diario"]:
            dados["resumo_diario"][hoje_str] = {
                "wins": 0, "losses": 0, "winrate": 0.0,
                "max_seq_win": 0, "max_seq_loss": 0,
                "sequencias_win":  [], "sequencias_loss": [],
                "seq_win_atual": 0, "seq_loss_atual": 0,
                "inicio_seq_win": "", "inicio_seq_loss": ""
            }
        rd = dados["resumo_diario"][hoje_str]

        if win:
            rd["wins"] += 1
            rd["seq_win_atual"]  = rd.get("seq_win_atual", 0) + 1
            # Fecha sequência de loss se havia
            seq_l = rd.get("seq_loss_atual", 0)
            if seq_l >= 2:
                dados["sequencias"]["losses"].append({
                    "tamanho": seq_l,
                    "inicio":  rd.get("inicio_seq_loss", "—"),
                    "fim":     hora_str[:5],
                    "data":    hoje_str
                })
            rd["seq_loss_atual"]  = 0
            rd["inicio_seq_loss"] = ""
            if rd["seq_win_atual"] == 1:
                rd["inicio_seq_win"] = hora_str[:5]
            if rd["seq_win_atual"] > rd["max_seq_win"]:
                rd["max_seq_win"] = rd["seq_win_atual"]
        else:
            rd["losses"] += 1
            rd["seq_loss_atual"] = rd.get("seq_loss_atual", 0) + 1
            # Fecha sequência de win se havia
            seq_w = rd.get("seq_win_atual", 0)
            if seq_w >= 2:
                dados["sequencias"]["wins"].append({
                    "tamanho": seq_w,
                    "inicio":  rd.get("inicio_seq_win", "—"),
                    "fim":     hora_str[:5],
                    "data":    hoje_str
                })
            rd["seq_win_atual"]   = 0
            rd["inicio_seq_win"]  = ""
            if rd["seq_loss_atual"] == 1:
                rd["inicio_seq_loss"] = hora_str[:5]
            if rd["seq_loss_atual"] > rd["max_seq_loss"]:
                rd["max_seq_loss"] = rd["seq_loss_atual"]

        # Atualiza winrate do dia
        total_hoje = rd["wins"] + rd["losses"]
        rd["winrate"] = round(rd["wins"] / total_hoje * 100, 1) if total_hoje else 0.0

        # Mantém histórico limitado (últimos 10.000)
        dados["historico"] = dados["historico"][-10000:]
        # Mantém sequências dos últimos 30 dias
        dados["sequencias"]["wins"]   = dados["sequencias"]["wins"][-500:]
        dados["sequencias"]["losses"] = dados["sequencias"]["losses"][-500:]

        # ── Salva ─────────────────────────────────────────────────
        try:
            with open(LOSS_JSON_FILE, "w", encoding="utf-8") as _f:
                _json.dump(dados, _f, ensure_ascii=False, indent=2)
        except Exception as _e:
            log.warning(f"⚠️ Erro ao salvar {LOSS_JSON_FILE}: {_e}")

    # alias para compatibilidade com chamadas existentes
    def _registrar_loss_json(self, win: bool = False) -> None:
        self._registrar_resultado_json(win=win)

    async def _send_async(self, text: str, markup=None) -> Optional[int]:
        if not await self._ensure_tg_client():
            log.error("_send_async: Telethon não conectado")
            return None

        # ── Converte markup InlineKeyboard → botões Telethon ──────
        buttons = None
        if markup:
            from telethon.tl.custom import Button
            rows = []
            for row in markup.keyboard:
                btn_row = []
                for btn in row:
                    if btn.callback_data:
                        btn_row.append(Button.inline(btn.text, data=btn.callback_data.encode()))
                    elif btn.url:
                        btn_row.append(Button.url(btn.text, btn.url))
                if btn_row:
                    rows.append(btn_row)
            buttons = rows if rows else None

        # ── Trunca texto longo (Telegram: máx 4096 chars) ─────────
        if len(text) > 4000:
            text = text[:3990] + "\n<i>…[truncado]</i>"

        # ── Retry com backoff progressivo rápido ──────────────────
        backoffs = (0.3, 0.8, 2.0)
        for tentativa, wait in enumerate(backoffs, 1):
            try:
                msg = await self._tg_client.send_message(
                    self._tg_entity,
                    text,
                    parse_mode="html",
                    buttons=buttons,
                    link_preview=False,
                )
                return msg.id
            except Exception as e:
                err_str = str(e)
                log.warning(f"_send_async tentativa {tentativa}/3 | {type(e).__name__}: {err_str!r}")
                if tentativa < 3:
                    if "flood" in err_str.lower() or "420" in err_str:
                        await asyncio.sleep(wait * 4)
                    else:
                        await asyncio.sleep(wait)
                        await self._ensure_tg_client()
        log.error("_send_async falhou após 3 tentativas")
        return None

    async def _edit_async(self, msg_id: int, text: str) -> None:
        if not await self._ensure_tg_client():
            return
        if len(text) > 4000:
            text = text[:3990] + "\n<i>…[truncado]</i>"
        for tentativa in range(1, 4):
            try:
                await self._tg_client.edit_message(
                    self._tg_entity, msg_id, text,
                    parse_mode="html", link_preview=False,
                )
                return
            except Exception as e:
                log.warning(f"_edit_async tentativa {tentativa}/3 | {type(e).__name__}: {e!r}")
                if tentativa < 3:
                    await asyncio.sleep(0.4 * tentativa)

    async def _sticker_async(self, sticker_id: str) -> None:
        return

    async def _carregar_historico_inicial(self) -> None:
        """
        Carrega o máximo de histórico disponível da Blaze (MINERADOR_PAGINAS páginas).
        - history_buffer (últimas 500): usado para Markov, Regime, Motor em tempo real
        - historico_completo (tudo): usado para retroalimentar AutoLearner
        """
        log.info(f"📥 Carregando histórico inicial ({MINERADOR_PAGINAS} páginas)...")
        await self._ensure_session()
        color_map = {0: "B", 1: "V", 2: "P"}
        historico = []
        historico_completo = []   # inclui roll para o BrancoDetector
        paginas_ok = 0
        for pagina in range(1, MINERADOR_PAGINAS + 1):
            url = (f"{self.cfg.url}/api/singleplayer-originals/originals"
                   f"/roulette_games/recent/1?page={pagina}")
            try:
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status != 200: break
                    data = await r.json()
                    if not data: break
                    for item in data:
                        cor = color_map.get(item.get("color"), "?")
                        roll_val = item.get("roll")
                        if cor != "?" and roll_val is not None and 0 <= int(roll_val) <= 14:
                            roll_val = int(roll_val)
                            historico.append(cor)
                            try:
                                dt_str = item.get("created_at", "")
                                hora_item = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%H")
                            except Exception:
                                hora_item = datetime.now().strftime("%H")
                            historico_completo.append({
                                "cor":  cor,
                                "roll": roll_val,
                                "hora": hora_item,
                            })
                    paginas_ok += 1
            except Exception as e:
                log.warning(f"Histórico inicial página {pagina}: {e}")
                break
            await asyncio.sleep(0.02)  # mínimo para ceder o loop, sem gargalo

        if not historico:
            log.warning("Histórico inicial vazio.")
            return

        historico.reverse()           # ordem cronológica crescente
        historico_completo.reverse()  # idem

        # Buffer operacional: últimas 500 para Markov/Motor/Regime (tempo real)
        self.history_buffer = historico[-500:]
        self.markov.feed(self.history_buffer)

        # ── Regime com histórico recente ───────────────────────────
        self.regime.atualizar(self.history_buffer)

        hist_vp = [c for c in historico if c in ("V", "P")]
        total   = len(self.history_buffer)
        v       = self.history_buffer.count("V")
        p       = self.history_buffer.count("P")
        b       = self.history_buffer.count("B")
        log.info(
            f"Histórico inicial: {len(historico)} rodadas brutas | "
            f"{len(hist_vp)} VP | {paginas_ok} páginas | "
            f"buffer={total} | 🔴{v} ⚫{p} ⚪{b}"
        )

        resultado_motor = _motor_decisao.analisar(self.history_buffer)
        motor_msg       = _motor_decisao.build_telegram_msg(resultado_motor)

        # ── Inicializa VermelhoEngine com histórico real ───────────
        if self.vermelho_integrador:
            self.vermelho_integrador.inicializar_historico(self.history_buffer)
            log.info("🔴 VermelhoEngine: histórico real carregado")

        # ── Minera padrões matemáticos antes do branco ─────────────
        brancos_no_hist = sum(1 for r in historico_completo if r["cor"] == "B")
        log.info(f"⚪ BrancoDetector: iniciando mineração ({brancos_no_hist} brancos no histórico)...")
        novos_branco = _branco_detector.minerar(historico_completo)
        log.info(f"⚪ BrancoDetector: {novos_branco} padrões novos | total={len(_branco_detector._padroes)}")

        # ── Inicializa NumeroStats com histórico completo ───────────
        if _NUMERO_STATS_DISPONIVEL:
            log.info("🔢 NumeroStats: inicializando com histórico...")
            _numero_stats.inicializar_historico(historico_completo)
            log.info("🔢 GrupoSeco: inicializando pares...")
            _grupo_seco.inicializar_historico(historico_completo)
            # ── SequenciaStats ────────────────────────────────────
            try:
                from numero_stats import _sequencia_stats
                log.info("🔢 SequenciaStats: inicializando sequências VP...")
                _sequencia_stats.inicializar_historico(historico_completo)
                log.info("🔢 SequenciaStats: pronto!")
            except Exception as e:
                log.warning(f"SequenciaStats init: {e}")
            log.info("🔢 NumeroStats + GrupoSeco + SequenciaStats: prontos!")

        # ── Carrega histórico no NumeroHoraFavorita ─────────────────
        log.info("🕐 NumeroHoraFavorita: carregando histórico...")
        _numero_hora.registrar_historico(historico_completo)

        matriz_msg = await self.build_matrix_msg()
        if matriz_msg:
            self.last_matrix_msg_id = await self._send_async(matriz_msg)
            self.last_matrix_time   = time.time()
        # Log interno apenas — sem enviar para o Telegram
        log.info(
            f"✅ Histórico carregado: {len(historico)} rodadas "
            f"({len(hist_vp)} VP | {paginas_ok} páginas) | regime={self.regime.regime}"
        )


    async def build_matrix_msg(self) -> Optional[str]:
        """
        Matriz visual do histórico da Blaze — igual à tela do jogo.
        - 30 colunas × N linhas (últimas 300 rodadas)
        - Ordem: da esquerda para direita, linha por linha (mais antigo no topo)
        - Nova rodada entra no final (última posição)
        - Cores: 🔴 Vermelho | ⚫ Preto | ⚪ Branco
        - Topo: % de cada cor nas últimas 300 rodadas
        """
        try:
            # Pega o histórico completo (V, P, B) — não filtra brancos
            hist = [c for c in self.history_buffer if c in ("V", "P", "B")]
            if len(hist) < 10:
                return None

            COLS   = 30
            TOTAL  = 300   # últimas 300 rodadas = 10 linhas de 30
            ultimas = hist[-TOTAL:]

            CE = {"V": "🔴", "P": "⚫", "B": "⚪"}

            # ── % de cada cor ─────────────────────────────────────
            n     = len(ultimas)
            cnt_v = ultimas.count("V")
            cnt_p = ultimas.count("P")
            cnt_b = ultimas.count("B")
            pct_v = cnt_v / n * 100
            pct_p = cnt_p / n * 100
            pct_b = cnt_b / n * 100

            # Quem domina
            if cnt_v > cnt_p:
                dom = f"🔴 <b>Vermelho domina ({pct_v:.0f}%)</b>"
            elif cnt_p > cnt_v:
                dom = f"⚫ <b>Preto domina ({pct_p:.0f}%)</b>"
            else:
                dom = "⚖️ <b>Equilíbrio</b>"

            # ── Monta linhas da matriz ────────────────────────────
            linhas_mat = []
            for i in range(0, len(ultimas), COLS):
                bloco = ultimas[i:i + COLS]
                linhas_mat.append("".join(CE.get(c, "?") for c in bloco))

            # ── Últimas 5 cores para "próxima tendência" ──────────
            recentes_vp = [c for c in hist[-10:] if c in ("V", "P")]
            seq_recente = "".join(CE.get(c, "") for c in recentes_vp[-5:])

            return (
                f"🎲 <b>Matriz — últimas {n} rodadas</b>\n"
                f"🔴 {pct_v:.0f}%  ⚫ {pct_p:.0f}%  ⚪ {pct_b:.0f}%  │  {dom}\n"
                f"{'─' * 15}\n"
                + "\n".join(linhas_mat) +
                f"\n{'─' * 15}\n"
                f"⏱️ Recentes: {seq_recente}\n"
                f"{self.regime.linha_status()}"
            )
        except Exception as e:
            log.warning(f"build_matrix_msg erro: {e}")
            return None

    async def _executar_aposta(self, color: str) -> float:
        """Executa aposta no AutoBet e retorna o valor apostado."""
        if not self.autobet or self.autobet._pausado:
            return 0.0
        result = await self.autobet.place_bet(color)
        if result.get("ok"):
            return result.get("valor", 0.0)
        return 0.0

    async def _registrar_resultado_autobet(self, win: bool, valor: float) -> None:
        """Registra resultado no AutoBet e envia status se necessário."""
        if not self.autobet:
            return
        res = self.autobet.register_result(win, valor)
        if res.get("pausado"):
            await self._send_async(
                f"🎰 <b>AutoBet {'GANHO' if win else 'PERDA'}</b>\n"
                f"⛔ <b>{res['motivo_pausa']}</b>\n"
                f"📊 PnL sessão: R${res['pnl_sessao']:.2f}"
            )

    async def _send_gale_msg(self, roll: int, color: str, gale_num: int) -> None:
        cor_emoji    = COLOR_LETTER_TO_EMOJI.get(color, "❓")
        aposta_emoji = COLOR_LETTER_TO_EMOJI.get(self.bet.color, "❓")
        cor_aposta   = COLOR_LETTER_TO_LABEL.get(self.bet.color, self.bet.color or "?")
        valor_aposta = self.gestor_banca.get_valor_aposta()
        restantes    = self.bet.gale_max - gale_num
        barra_gale   = "🟥" * gale_num + "⬜" * restantes

        autobet_gale = ""
        if self.autobet and not self.autobet._pausado:
            modo = "DRY" if self.cfg.autobet.dry_run else "REAL"
            autobet_gale = (
                f"\n🎰 AutoBet <b>{modo}</b>: R$ <b>{self.autobet._get_aposta_nivel():.2f}</b>"
            )

        await self._send_async(
            f"⚠️ <b>GALE {gale_num}/{self.bet.gale_max}</b>  {barra_gale}\n"
            f"{'─' * 20}\n"
            f"🎲 Saiu: {cor_emoji} <b>| {roll} |</b>\n"
            f"♻️ Mantendo: {aposta_emoji} <b>{cor_aposta}</b>\n"
            f"💰 Aposta: <b>R$ {valor_aposta:.2f}</b>  │  "
            f"Restantes: <b>{restantes}</b>"
            f"{autobet_gale}"
        )

    async def _send_entry_signal(
        self, color: str, source: str, confirmadores: list,
        score_dict: dict = None,
        seq_bloco: str = "",
        origem: str = "padrao") -> None:

        emoji     = COLOR_LETTER_TO_ENTRY_EMOJI.get(color, "❓")
        cor_label = COLOR_LETTER_TO_LABEL.get(color, color)
        streak_info = self.cooldown.streak_info()

        key     = (tuple(self.bet.pattern or []), color)
        ks      = PatternNameRegistry._key_str(key)
        name    = self.pattern_names.get_name(key)
        rec     = self.pattern_records.get(ks)
        pat_str = "".join(
            COLOR_LETTER_TO_EMOJI.get(str(c), str(c)) for c in (self.bet.pattern or []))

        valor_aposta = self.gestor_banca.get_valor_aposta()
        hora_atual   = datetime.now().strftime("%H:%M:%S")

        # ── SimulacaoGale: registra novo sinal para monitorar G2 ──
        if self.cfg.max_gale == 1:
            _sim_gale.iniciar_sinal(color, name)

        # ── Score visual ──────────────────────────────────────────
        score_str = ""
        if score_dict:
            sc    = int(score_dict["score"])
            barra = "█" * (sc // 10) + "░" * (10 - (sc // 10))
            score_str = (
                f"⚡ <b>{sc}/100</b>  <code>[{barra}]</code>  "
                f"{score_dict['emoji']} <i>{score_dict['conselho']}</i>\n"
            )

        # ── Bloco do padrão ───────────────────────────────────────
        if rec and rec.total > 0:
            ranking    = self._get_pattern_ranking(ks)
            streak_pad = ""
            if rec.current_win_streak > 0:
                streak_pad = f"  🔥{rec.current_win_streak}"
            elif rec.current_loss_streak > 0:
                streak_pad = f"  💀{rec.current_loss_streak}"

            # ── Máxima isolada do padrão exato ────────────────────
            padrao_seco_linha = ""
            try:
                from numero_stats import _sequencia_stats
                padrao_completo = list(self.bet.pattern or []) + [color]
                mx_pad, seco_pad, _ = _sequencia_stats._calcular(padrao_completo)
                if mx_pad > 0:
                    pct_pad  = int(seco_pad / max(1, mx_pad) * 100)
                    def _b(p, s=6): return "█"*int(round(min(p,100)/100*s))+"░"*(s-int(round(min(p,100)/100*s)))
                    urg_pad  = " 🔴" if pct_pad>=90 else (" 🟠" if pct_pad>=75 else (" 🟡" if pct_pad>=55 else ""))
                    padrao_seco_linha = (
                        f"⏱️ Padrão isolado:  "
                        f"seco <b>{seco_pad}</b>  máx <b>{mx_pad}</b>  "
                        f"<code>[{_b(pct_pad)}]</code>{urg_pad}\n"
                    )
            except Exception:
                pass

            historico_bloco = (
                f"🏷️ <b>[{name}]</b>  {ranking}\n"
                f"<code>{pat_str} → {emoji}</code>\n"
                f"✅ <b>{rec.wins}W</b>  ❌ <b>{rec.losses}L</b>  "
                f"📊 <b>{rec.accuracy:.0f}%</b>{streak_pad}\n"
                f"{padrao_seco_linha}"
                f"{score_str}"
            )
        else:
            historico_bloco = (
                f"🏷️ <b>[{name}]</b>  🆕\n"
                f"<code>{pat_str} → {emoji}</code>\n"
                f"⚠️ <i>1ª entrada</i>\n"
                f"{score_str}"
            )

        # ── Nível de assertividade do padrão ─────────────────────
        # Define banner de destaque baseado na % de acerto
        acc_atual = rec.accuracy if (rec and rec.total >= 5) else 0.0
        total_atual = rec.total if rec else 0

        if acc_atual >= 100 and total_atual >= 11:
            # Elite: pisca com 🔵 dos dois lados
            banner_elite = (
                f"🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵\n"
                f"🔵  ⚡ PADRÃO ELITE ⚡  🔵\n"
                f"🔵  {acc_atual:.0f}% | {total_atual} entradas  🔵\n"
                f"🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵\n"
            )
        elif acc_atual >= 95 and total_atual >= 8:
            banner_elite = (
                f"🔵🔵 PADRÃO FORTE 🔵🔵\n"
                f"📊 {acc_atual:.0f}% | {total_atual} entradas\n"
            )
        elif acc_atual >= 90 and total_atual >= 5:
            banner_elite = f"🔵 Padrão confiável ({acc_atual:.0f}%)\n"
        else:
            banner_elite = ""

        # ── Confirmação multi-padrão ──────────────────────────────
        dupla_str = ""
        if confirmadores and len(confirmadores) >= 2:
            COR_E  = {"V": "🔴", "P": "⚫"}
            partes = [
                f"  [{src}] "
                + "".join(COLOR_LETTER_TO_EMOJI.get(str(c), str(c)) for c in pat)
                + f"→{COR_E.get(pred,'?')}"
                for pat, pred, src in confirmadores
            ]
            dupla_str = (
                f"🔗 <b>{len(confirmadores)} padrões confirmam</b>\n"
                + "\n".join(partes) + "\n"
            )

        # ── Autobet ───────────────────────────────────────────────
        autobet_line = ""
        if self.autobet and not self.autobet._pausado:
            modo = "DRY" if self.cfg.autobet.dry_run else "REAL"
            autobet_line = (
                f"🎰 AutoBet <b>{modo}</b>: R$ <b>{self.autobet._get_aposta_nivel():.2f}</b> "
                f"(nív. {self.autobet._nivel_atual})\n"
            )
        elif self.autobet and self.autobet._pausado:
            autobet_line = f"🎰 AutoBet ⛔ <i>{self.autobet._motivo_pausa}</i>\n"

        # ── Header por origem ─────────────────────────────────────
        if origem == "autonomo":
            _cat_em_a  = self._cat_emoji(self._cat_atual)
            _cat_lbl_a = self._cat_label(self._cat_atual)
            header = (
                f"╔══════════════════╗\n"
                f"║  🤖  SINAL AUTO  ║\n"
                f"╚══════════════════╝\n\n"
                f"{_cat_em_a} <b>CAT{self._cat_atual} — {_cat_lbl_a}</b>\n"
                f"🎯 <b>ENTRAR:</b>  {emoji}  <b>{cor_label.upper()}</b>\n"
                f"♻️ Gale máx: <b>{self.bet.gale_max}</b>  │  🕐 {hora_atual}\n"
                f"📡 <b>Motor Autônomo VP</b>\n"
            )
        else:
            badge = {"C": "🏅 ELITE", "B": "⭐ TOP", "A": "✅ NORMAL"}.get(source, f"📂 {source}")
            # Categoria sempre presente em todos os headers
            _cat_em  = self._cat_emoji(self._cat_atual)
            _cat_lbl = self._cat_label(self._cat_atual)
            _cat_str = f"{_cat_em} <b>CAT{self._cat_atual} — {_cat_lbl}</b>\n"

            if acc_atual >= 100 and total_atual >= 11:
                header = (
                    f"🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵\n"
                    f"🔵  🚨  SINAL VP!  🔵\n"
                    f"🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵\n\n"
                    f"{_cat_str}"
                    f"🎯 <b>ENTRAR:</b>  {emoji}  <b>{cor_label.upper()}</b>\n"
                    f"♻️ Gale máx: <b>{self.bet.gale_max}</b>  │  🕐 {hora_atual}\n"
                    f"📂 Lista <b>{badge}</b>\n"
                )
            elif acc_atual >= 95 and total_atual >= 8:
                header = (
                    f"🔵 🚨 <b>SINAL VP!</b> 🔵\n\n"
                    f"{_cat_str}"
                    f"🎯 <b>ENTRAR:</b>  {emoji}  <b>{cor_label.upper()}</b>\n"
                    f"♻️ Gale máx: <b>{self.bet.gale_max}</b>  │  🕐 {hora_atual}\n"
                    f"📂 Lista <b>{badge}</b>\n"
                )
            else:
                header = (
                    f"╔══════════════════╗\n"
                    f"║  🚨  SINAL VP!   ║\n"
                    f"╚══════════════════╝\n\n"
                    f"{_cat_str}"
                    f"🎯 <b>ENTRAR:</b>  {emoji}  <b>{cor_label.upper()}</b>\n"
                    f"♻️ Gale máx: <b>{self.bet.gale_max}</b>  │  🕐 {hora_atual}\n"
                    f"📂 Lista <b>{badge}</b>\n"
                )

        # ── Padrão seguinte (sucessores) — usa cache do __init__ ──
        succ_bloco = ""
        try:
            import json as _json
            _pat_key    = _json.dumps([list(self.bet.pattern or []), color])
            _d          = self._sucessores_cache.get(_pat_key)
            _hist_total = _d.get("hist_count", 0) if _d else 0

            # Exibe se base histórica >= 25 ocorrências reais
            if _d and _d.get("sucessores") and _hist_total >= 25:
                _CE       = {"V": "🔴", "P": "⚫"}
                _MEDALHAS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣"]

                # Ordena por contagem real decrescente (o que mais apareceu depois)
                _succs = sorted(
                    _d["sucessores"],
                    key=lambda _x: _x.get("count", _x.get("freq_hist", 0)),
                    reverse=True
                )[:6]

                _linhas = []
                for _i, _s in enumerate(_succs):
                    # Pega sequência — compatível com ambos os formatos de JSON
                    _seq_raw = _s.get("seq") or _s.get("pat") or []
                    _pat_b   = "".join(_seq_raw) if isinstance(_seq_raw, list) else str(_seq_raw)
                    _tam_b   = _s.get("tam", len(_pat_b))
                    _count   = _s.get("count", _s.get("freq_hist", 0))
                    _pct     = _s.get("pct_aparece", _s.get("pct", 0))
                    _pred_b  = _s.get("pred")
                    _acc     = _s.get("acc")
                    _wr      = _s.get("wr_banco")
                    _w       = _s.get("wins_banco", _s.get("wins", 0))
                    _l       = _s.get("losses_banco", _s.get("losses", 0))
                    _sk      = _s.get("streak_win", 0)
                    _tem_b   = _s.get("tem_banco", _acc is not None)
                    _medal   = _MEDALHAS[_i] if _i < len(_MEDALHAS) else "  "
                    _streak_txt = f" 🔥{_sk}W" if _sk >= 2 else ""
                    _emoji_c = _CE.get(_pred_b, "") if _pred_b else ""

                    # Bloco de qualidade: mostra acc se tem banco
                    if _tem_b and _acc is not None:
                        _qual      = "🟢" if _acc >= 80 else "🟡" if _acc >= 60 else "🔴"
                        _banco_txt = f"  {_qual} {_emoji_c} acc:<b>{_acc:.0f}%</b> ({_w}W/{_l}L)"
                    elif _wr is not None:
                        _qual      = "🟢" if _wr >= 0.80 else "🟡" if _wr >= 0.60 else "🔴"
                        _banco_txt = f"  {_qual} {_emoji_c} acc:<b>{_wr*100:.0f}%</b> ({_w}W/{_l}L)"
                    else:
                        _banco_txt = f"  ⬜ {_emoji_c} <i>sem histórico</i>"

                    _linhas.append(
                        f"{_medal} <code>{_pat_b}</code> <b>{_pct:.0f}%</b> das vezes ({_count}x)"
                        f"{_banco_txt}{_streak_txt}"
                    )

                if _linhas:
                    _top     = _succs[0]
                    _top_seq = _top.get("seq") or _top.get("pat") or []
                    _top_pat = "".join(_top_seq) if isinstance(_top_seq, list) else str(_top_seq)
                    _top_pct = _top.get("pct_aparece", _top.get("pct", 0))
                    _top_tam = _top.get("tam", len(_top_pat))
                    _top_em  = _CE.get(_top.get("pred"), "") if _top.get("pred") else ""
                    succ_bloco = (
                        f"{'─' * 20}\n"
                        f"📊 <b>Padrões que vieram depois</b>  "
                        f"<i>({_hist_total}x reais)</i>\n"
                        f"⚡ Mais frequente: <code>{_top_pat}</code>({_top_tam}) "
                        f"{_top_em} <b>{_top_pct:.0f}%</b>\n"
                        + "\n".join(_linhas) + "\n"
                    )
        except Exception as _e:
            log.debug(f"Sucessores bloco: {_e}")

        # ── Sequências ────────────────────────────────────────────
        extra_bloco = ""
        if seq_bloco:
            extra_bloco += f"{'─' * 20}\n{seq_bloco}\n"

        # ── Monta mensagem final ──────────────────────────────────
        msg = (
            f"{header}"
            f"{'─' * 20}\n"
            f"💰 Entrada: <b>R$ {valor_aposta:.2f}</b>  │  "
            f"Banca: R$ <b>{self.gestor_banca.banca_atual:.2f}</b>\n"
            f"{autobet_line}"
            f"{dupla_str}"
            f"{'─' * 20}\n"
            f"{banner_elite}"
            f"📊 <b>PADRÃO</b>\n"
            f"{historico_bloco}"
            f"{succ_bloco}"
            f"{extra_bloco}"
            f"{'─' * 20}"
        )

        # ── MenteViva: veredito contextual ───────────────────────
        try:
            hora_mv = datetime.now().strftime("%H:%M:%S")
            veredito_bloco = _mente_viva.pensar_e_veredictar(
                score            = score_dict.get("score", 80.0) if score_dict else 80.0,
                hora             = hora_mv,
                predicao         = color,
                history          = self.history_buffer,
                regime           = self.regime.regime,
                loss_streak_atual= rec.current_loss_streak if rec else 0,
                win_streak_atual = rec.current_win_streak  if rec else 0,
                nome_padrao      = name,
            )
            msg = msg + "\n" + veredito_bloco
        except Exception as _e:
            log.debug(f"MenteViva sinal: {_e}")

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "🎰 Apostar na Blaze", url="https://blaze.bet.br/pt/games/double"))
        await self._send_async(msg, markup)

        # ── Ativa confirmador pós-sinal ───────────────────────────
        self._confirma_pred   = color
        self._confirma_pat    = "".join(str(c) for c in (self.bet.pattern or []))
        self._confirma_nome   = name
        self._confirma_buffer = []
        self._confirma_ativo  = True
        log.info(f"🔍 Confirmador ativado | {self._confirma_pat}→{color} | "
                 f"aguardando {self._confirma_min}x {color} em {self._confirma_max} rodadas VP")


    async def _tg_worker(self) -> None:
        """
        Worker dedicado que consome a fila _tg_queue em ordem FIFO.
        Rate-limit: 1 msg/seg por chat (limite do Telegram).
        Sinais críticos (entrada/win/loss) são enviados direto,
        sem passar pela fila, para chegada imediata.
        """
        _last_send: float = 0.0
        _MIN_INTERVAL     = 0.35  # 350ms entre msgs da fila ≈ ~3 msg/s seguro

        while True:
            try:
                text, markup, fut = await self._tg_queue.get()

                # Respeita intervalo mínimo entre mensagens da fila
                agora = time.time()
                espera = _MIN_INTERVAL - (agora - _last_send)
                if espera > 0:
                    await asyncio.sleep(espera)

                msg_id = await self._send_async(text, markup)
                _last_send = time.time()

                if fut and not fut.done():
                    fut.set_result(msg_id)
                self._tg_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"_tg_worker erro: {e}")
                await asyncio.sleep(0.5)

    async def _enqueue(self, text: str, markup=None) -> Optional[int]:
        """
        Enfileira mensagem para envio assíncrono via _tg_worker.
        Para sinais críticos (entrada, win, loss) — usa send direto.
        """
        loop = asyncio.get_running_loop()
        fut  = loop.create_future()
        try:
            self._tg_queue.put_nowait((text, markup, fut))
            return await asyncio.wait_for(fut, timeout=15)
        except asyncio.QueueFull:
            log.warning("_tg_queue cheia — enviando diretamente")
            return await self._send_async(text, markup)
        except asyncio.TimeoutError:
            log.warning("_enqueue timeout de 15s")
            return None

    async def run(self) -> None:
        log.info("🔌 Conectando via Telethon MTProto...")
        tg_ok = await self._ensure_tg_client()
        if not tg_ok:
            log.error("❌ Telethon não conectou — verifique [telegram] no config.ini")
        self._start_polling()
        asyncio.create_task(self._tg_worker())  # inicia worker de fila de envio
        log.info("🔴⚫ BlazeBot VP ONLINE — Padrões 5-6 | 11 testes | 90% | Decisão Autônoma")

        autobet_msg = ""
        if self.autobet:
            log.info("🔐 AutoBet: realizando login na Blaze...")
            login_ok = await self.autobet.ensure_token()
            if login_ok:
                saldo = await self.autobet.get_balance()
                modo  = "🔵 DRY-RUN" if self.cfg.autobet.dry_run else "🟢 BANCA REAL"
                saldo_txt = f"R${saldo:.2f}" if saldo is not None else "N/D"
                autobet_msg = (
                    f"\n\n🎰 <b>AutoBet {modo} ATIVO</b> ✅\n"
                    f"💰 Saldo Blaze: <b>{saldo_txt}</b>\n"
                    f"📈 Paroli Base: R${self.cfg.autobet.aposta_base:.2f} | "
                    f"Níveis: {self.cfg.autobet.max_niveis}\n"
                    f"🛑 Stop: R${self.cfg.autobet.stop_loss:.2f} | "
                    f"🎯 Gain: R${self.cfg.autobet.take_profit:.2f}"
                )
            else:
                autobet_msg = "\n\n⚠️ <b>AutoBet: login FALHOU</b> — verifique [blaze_auth] no config.ini"

        # ── Aviso crítico apenas se max_gale=0 ───────────────────
        if self.cfg.max_gale == 0:
            log.warning("⚠️ max_gale=0 no config.ini — SEM GALE ativo.")
            await self._send_async(
                "⚠️ <b>ATENÇÃO: max_gale=0</b> — SEM GALE ativo!\n"
                "Mude para <code>max_gale = 2</code> no config.ini"
            )

        await self._send_async(
            f"🤖 <b>BlazeBot VP online</b>  ⏳ Carregando histórico..."
        )
        await self._carregar_historico_inicial()
        self.last_relatorio_3min = time.time()
        asyncio.create_task(self.minerador._executar())
        while True:
            try:
                await self._loop_tick()
                await self.minerador.rodar_se_necessario()
                # ── Relatório automático de 3 em 3 minutos ────────
                agora = time.time()
                if agora - self.last_relatorio_3min >= RELATORIO_INTERVALO_SEG:
                    self.last_relatorio_3min = agora
                    asyncio.create_task(self._send_relatorio_3min())
            except Exception as e:
                log.error(f"Erro no loop: {e}")
            await asyncio.sleep(0.3)  # poll 3x/s para não perder transição de status

    async def _loop_tick(self) -> None:
        status, roll, color = await self.get_status()
        if not status or status == self.last_status:
            return

        prev_status      = self.last_status
        self.last_status = status

        if status == "waiting":
            agora = time.time()
            # Debounce: ignora "waiting" se chegou < 3s após outro "waiting"
            # Protege contra bounce na API da Blaze que dispara 2 sinais
            if agora - self._last_waiting_ts < 3.0 and prev_status == "waiting":
                log.debug("⚡ Debounce 'waiting' — bounce de status ignorado")
                return
            self._last_waiting_ts = agora
            await self._on_waiting()
        elif status == "rolling":
            await self._on_rolling(roll, color)
        elif status == "complete":
            await self._on_complete()

    async def _on_waiting(self) -> None:
        if self.pending_msg_id:
            self._delete(self.pending_msg_id)
            self.pending_msg_id = None
        # ── Detecta cor dominante para o próximo sinal ─────────────
        self.cor_dom_ultimo = self._detectar_cor_dominante()
        # ── Lock: garante que apenas UMA chamada processe o sinal ──
        if self._signal_lock.locked():
            log.debug("🔒 _on_waiting: lock ativo — chamada ignorada (anti-duplo)")
            return
        async with self._signal_lock:
            await self._verificar_e_enviar_sinal()

    async def _on_rolling(self, roll: int, color: str) -> None:
        if not self.bet.active:
            return
        result  = self._evaluate_result(color)
        gale_at = self.bet.gale_current
        source  = self.bet.source or "AUTO"

        log.info(
            f"🎲 ROLLING | saiu={color}({roll}) | apostei={self.bet.color} | "
            f"result={result} | gale={gale_at}/{self.bet.gale_max} | fonte={source}"
        )

        if result in ("WIN", "WIN_BRANCO"):
            eh_branco = (result == "WIN_BRANCO")
            pattern_used    = list(self.bet.pattern or [])
            prediction_used = self.bet.color or color
            # Branco paga 14x independente do que foi apostado
            payout          = 14.0 if eh_branco else COLOR_PAYOUT.get(prediction_used, 2.0)
            valor_foi       = self.bet.valor_apostado
            self.gestor_banca.registrar_win(payout, gale_attempt=gale_at)
            self.bet.reset()
            self.cooldown.register_win(prediction_used)
            self.ab.register(source if source in ("A","B","C","D") else "A", win=True)
            self.stats.register_win(gale_at)
            self._verificar_cor_dominante_e_registrar(True)

            gale_txt    = f"  (Gale {gale_at})" if gale_at > 0 else ""
            cor_emoji   = COLOR_LETTER_TO_EMOJI.get(color, "")
            _val_apost  = self.bet.valor_apostado if self.bet.valor_apostado > 0 else self.gestor_banca.entrada_base
            _lucro_win  = round(_val_apost * (payout - 1), 2)
            # ── Mensagem especial para WIN por branco ────────────────
            if eh_branco:
                asyncio.create_task(self._send_async(
                    f"⚪️✅ <b>WIN BRANCO{gale_txt}!</b>  <b>+R${_lucro_win:.2f}</b>  <i>(14x)</i>\n"
                    f"{'─' * 20}\n"
                    f"🛡️ <b>Proteção Branco ativada!</b> Saiu ⚪️ e contou como WIN\n"
                    f"💰 Saldo: <b>R$ {self.gestor_banca.banca_atual:.2f}</b>  │  "
                    f"Próxima: R$ <b>{self.gestor_banca.get_valor_aposta():.2f}</b>\n"
                    f"🔥 Sequência: <b>{self.stats.consecutive_wins}W</b>  │  "
                    f"📊 Acc: <b>{self.stats.accuracy:.0f}%</b>  "
                    f"({self.stats.wins}✅/{self.stats.losses}❌)"
                ))
            else:
                asyncio.create_task(self._send_async(
                    f"✅ <b>WIN{gale_txt}!</b>  {cor_emoji}  <b>+R${_lucro_win:.2f}</b>\n"
                    f"{'─' * 20}\n"
                    f"💰 Saldo: <b>R$ {self.gestor_banca.banca_atual:.2f}</b>  │  "
                    f"Próxima: R$ <b>{self.gestor_banca.get_valor_aposta():.2f}</b>\n"
                    f"🔥 Sequência: <b>{self.stats.consecutive_wins}W</b>  │  "
                    f"📊 Acc: <b>{self.stats.accuracy:.0f}%</b>  "
                    f"({self.stats.wins}✅/{self.stats.losses}❌)"
                ))
            if self.autobet and valor_foi > 0:
                asyncio.create_task(self._registrar_resultado_autobet(True, valor_foi))
            if pattern_used:
                self._register_pattern_result(pattern_used, prediction_used,
                                               win=True, gale_attempt=gale_at)
                nome_win = self.pattern_names.get_name((tuple(pattern_used), prediction_used))
                rec_win  = self.pattern_records.get(
                    PatternNameRegistry._key_str((tuple(pattern_used), prediction_used)))
                score_win = rec_win.accuracy if rec_win else 0.0
                _confusion.registrar(prediction_used, color, nome_win, score_win)
            tipo_win = "WIN_BRANCO ⚪️" if eh_branco else "WIN VP"
            log.info(f"{tipo_win} | cor={color} | gale={gale_at} | fonte={source}")
            # ── MenteViva aprende com este WIN ────────────────────
            try:
                _rec_win = self.pattern_records.get(
                    PatternNameRegistry._key_str((tuple(pattern_used), prediction_used))
                ) if pattern_used else None
                _mente_viva.aprender(
                    win              = True,
                    score            = float(getattr(_rec_win, "accuracy", 80.0)) if _rec_win else 80.0,
                    hora             = datetime.now().strftime("%H:%M:%S"),
                    predicao         = prediction_used,
                    history          = self.history_buffer,
                    regime           = self.regime.regime,
                    loss_streak_antes= _rec_win.current_loss_streak if _rec_win else 0,
                    win_streak_antes = _rec_win.current_win_streak  if _rec_win else 0,
                )
            except Exception as _e:
                log.debug(f"MenteViva win: {_e}")
            # ── SimulacaoGale ──────────────────────────────────────
            if gale_at == 0:
                _sim_gale.registrar_win_direto()
            elif gale_at == 1 and self.cfg.max_gale == 1:
                # WIN no gale 1 — não precisou do G2
                if _sim_gale._pendente:
                    nome_sg = self.pattern_names.get_name(
                        (tuple(pattern_used), prediction_used)) if pattern_used else "?"
                    _sim_gale._pendente["resultado"] = "WIN_G1"
                    _sim_gale._historico.append(dict(_sim_gale._pendente))
                    _sim_gale._pendente = {}
                    _sim_gale._save()
            # ── Pós-Mineração: registra sinal ─────────────────────
            if _pos_mineracao.monitorando and pattern_used:
                nome_pm = self.pattern_names.get_name((tuple(pattern_used), prediction_used))
                _pos_mineracao.registrar_sinal(
                    padrao_nome  = nome_pm,
                    padrao_cores = pattern_used + [prediction_used],
                    prediction   = prediction_used,
                    lista        = source if source in ("A","B","C","D") else "AUTO",
                    resultado    = "WIN",
                    gale         = gale_at,
                    cor_saiu     = color,
                )
                if _pos_mineracao.sinais_restantes == 0:
                    asyncio.create_task(self._send_async(
                        _pos_mineracao.relatorio_ultimo()
                    ))

        elif result == "LOSS":
            pattern_used    = list(self.bet.pattern or [])
            prediction_used = self.bet.color or color
            valor_foi       = self.bet.valor_apostado
            self.gestor_banca.registrar_loss(gale_attempt=gale_at)
            self.bet.reset()
            self.cooldown.register_loss(prediction_used)
            self.ab.register(source if source in ("A","B","C","D") else "A", win=False)
            self.stats.register_loss()
            self._verificar_cor_dominante_e_registrar(False)

            if pattern_used:
                key_loss = (tuple(pattern_used), prediction_used)
                ks_loss  = PatternNameRegistry._key_str(key_loss)
                self.pattern_loss_until[ks_loss] = time.time() + LOSS_BLOCK_IMEDIATO_SEG
                self.last_loss_pattern_ks = ks_loss
                nome_loss_log = self.pattern_names.get_name(key_loss)
                log.info(f"🔒 LOSS-BLOCK {LOSS_BLOCK_IMEDIATO_SEG//60}min | {pattern_used}→{prediction_used} [{nome_loss_log}]")

            _val_apost_loss = self.bet.valor_apostado if self.bet.valor_apostado > 0 else self.gestor_banca.entrada_base
            cor_emoji = COLOR_LETTER_TO_EMOJI.get(color, "")
            nome_pat  = self.pattern_names.get_name(
                (tuple(pattern_used), prediction_used)) if pattern_used else "?"

            # Verifica quantos losses consecutivos o padrão já tem
            ks_loss_check = PatternNameRegistry._key_str(
                (tuple(pattern_used), prediction_used)) if pattern_used else ""
            rec_loss_check = self.pattern_records.get(ks_loss_check)
            losses_consec  = rec_loss_check.losses_consecutivos_exclusao if rec_loss_check else 0

            aviso_excl = ""  # DESATIVADO

            em_janela_ruim = self.stats.janela_bloqueada()
            aviso_janela = (
                f"\n⚠️ <b>{MAX_LOSSES_NA_JANELA} losses na janela</b> — cautela"
            ) if em_janela_ruim else ""

            asyncio.create_task(self._send_async(
                f"❌ <b>LOSS!</b>  {cor_emoji}  <b>-R${_val_apost_loss:.2f}</b>\n"
                f"{'─' * 20}\n"
                f"💰 Saldo: <b>R$ {self.gestor_banca.banca_atual:.2f}</b>  │  "
                f"Próxima: R$ <b>{self.gestor_banca.get_valor_aposta():.2f}</b>\n"
                f"💀 Sequência: <b>{self.stats.consecutive_losses}L</b>  │  "
                f"📊 Acc: <b>{self.stats.accuracy:.0f}%</b>  "
                f"({self.stats.wins}✅/{self.stats.losses}❌)\n"
                f"🔒 [{nome_pat}] bloqueado por <b>{LOSS_BLOCK_IMEDIATO_SEG//60}min</b>"
                f"{aviso_excl}"
                f"{aviso_janela}"
            ))
            if self.autobet and valor_foi > 0:
                asyncio.create_task(self._registrar_resultado_autobet(False, valor_foi))
            if pattern_used:
                self._register_pattern_result(pattern_used, prediction_used, win=False)
                nome_loss = self.pattern_names.get_name((tuple(pattern_used), prediction_used))
                rec_loss  = self.pattern_records.get(
                    PatternNameRegistry._key_str((tuple(pattern_used), prediction_used)))
                score_loss = rec_loss.accuracy if rec_loss else 0.0
                _confusion.registrar(prediction_used, color, nome_loss, score_loss)
            self._check_loss_protection()
            log.info(f"LOSS VP | cor={color} | gale={gale_at} | fonte={source}")

            # ── SINAL INVERTIDO PÓS-LOSS ──────────────────────────
            # Inverte todas as cores do padrão que perdeu e manda novo sinal
            if pattern_used and prediction_used:
                _inv_map     = {"V": "P", "P": "V"}
                _pat_inv     = [_inv_map.get(c, c) for c in pattern_used]
                _pred_inv    = _inv_map.get(prediction_used, prediction_used)
                _emoji_inv   = COLOR_LETTER_TO_EMOJI.get(_pred_inv, "❓")
                _label_inv   = COLOR_LETTER_TO_LABEL.get(_pred_inv, _pred_inv)
                _cat_em_inv  = self._cat_emoji(self._cat_atual)
                _cat_lbl_inv = self._cat_label(self._cat_atual)
                _hora_inv    = datetime.now().strftime("%H:%M")
                _pat_inv_str = "".join(
                    COLOR_LETTER_TO_EMOJI.get(c, c) for c in _pat_inv
                )

                log.info(
                    f"🔄 SINAL INVERTIDO | {_pat_inv}→{_pred_inv} "
                    f"(original: {pattern_used}→{prediction_used})"
                )

                # Usa _fire para enviar IMEDIATAMENTE, sem esperar o loop
                self._fire(self._send_async(
                    f"🔄 <b>SINAL INVERTIDO</b>\n"
                    f"{'─' * 20}\n"
                    f"{_cat_em_inv} <b>CAT{self._cat_atual} — {_cat_lbl_inv}</b>\n"
                    f"🎯 <b>ENTRAR:</b>  {_emoji_inv}  <b>{_label_inv.upper()}</b>\n"
                    f"♻️ Gale máx: <b>{self.cfg.max_gale}</b>  │  🕐 {_hora_inv}\n"
                    f"{'─' * 20}\n"
                    f"📋 {_pat_inv_str} → {_emoji_inv}\n"
                    f"💡 <i>Cor oposta ao loss anterior</i>"
                ))

                # Ativa a aposta no sinal invertido imediatamente
                if not self.bet.active:
                    _gale_max_inv = self.cfg.max_gale if self.cfg.max_gale > 0 else (
                        GALE_MAX_VERMELHO if _pred_inv == "V" else GALE_MAX_PRETO
                    )
                    self.stats.total_signals += 1
                    self.bet.active       = True
                    self.bet.color        = _pred_inv
                    self.bet.pattern      = _pat_inv
                    self.bet.source       = "INV"
                    self.bet.gale_current = 0
                    self.bet.gale_max     = _gale_max_inv
                    self.bet.origem       = "invertido"
                    self.bet.valor_apostado = self.gestor_banca.get_valor_aposta()
                    log.info(
                        f"🔄 APOSTA INVERTIDA ATIVADA | {_pat_inv}→{_pred_inv} "
                        f"R${self.bet.valor_apostado:.2f}"
                    )
            # ── MenteViva aprende com este LOSS ───────────────────
            try:
                _rec_loss = self.pattern_records.get(
                    PatternNameRegistry._key_str((tuple(pattern_used), prediction_used))
                ) if pattern_used else None
                _mente_viva.aprender(
                    win              = False,
                    score            = float(getattr(_rec_loss, "accuracy", 80.0)) if _rec_loss else 80.0,
                    hora             = datetime.now().strftime("%H:%M:%S"),
                    predicao         = prediction_used,
                    history          = self.history_buffer,
                    regime           = self.regime.regime,
                    loss_streak_antes= _rec_loss.current_loss_streak if _rec_loss else 0,
                    win_streak_antes = _rec_loss.current_win_streak  if _rec_loss else 0,
                )
            except Exception as _e:
                log.debug(f"MenteViva loss: {_e}")
            # ── SimulacaoGale: LOSS no gale 1 → registra gale 2 simulado ──
            if gale_at == 1 and self.cfg.max_gale == 1 and _sim_gale._pendente:
                sim_linha = _sim_gale.registrar_gale2_simulado(color)
                if sim_linha:
                    asyncio.create_task(self._send_async(
                        f"{'─' * 20}\n{sim_linha}"
                    ))
            # ── Pós-Mineração: registra sinal ─────────────────────
            if _pos_mineracao.monitorando and pattern_used:
                nome_pm = self.pattern_names.get_name((tuple(pattern_used), prediction_used))
                _pos_mineracao.registrar_sinal(
                    padrao_nome  = nome_pm,
                    padrao_cores = pattern_used + [prediction_used],
                    prediction   = prediction_used,
                    lista        = source if source in ("A","B","C","D") else "AUTO",
                    resultado    = "LOSS",
                    gale         = gale_at,
                    cor_saiu     = color,
                )
                if _pos_mineracao.sinais_restantes == 0:
                    asyncio.create_task(self._send_async(
                        _pos_mineracao.relatorio_ultimo()
                    ))

        elif result == "GALE":
            if self.autobet and not self.autobet._pausado:
                asyncio.create_task(self._executar_aposta(self.bet.color))
            # ── SimulacaoGale: registra cor do gale 1 ─────────────
            if self.bet.gale_current == 1 and self.cfg.max_gale == 1:
                _sim_gale.registrar_gale1(color)
            await self._send_gale_msg(roll, color, self.bet.gale_current)
            log.info(f"GALE VP {self.bet.gale_current} | cor={color}")

    async def _on_complete(self) -> None:
        self.global_round += 1



        self.invalidar_cache_recent()
        res = await self.get_recent()
        if res and "items" in res:
            colors              = [i["color"] for i in reversed(res["items"])]
            self.history_buffer = colors[-500:]
            self.markov.feed(self.history_buffer)

            # ── Atualiza Regime a cada rodada completa ─────────────
            self.regime.atualizar(self.history_buffer)
            # ── Atualiza bias pós-branco ───────────────────────────
            self.bias_pos_branco.atualizar(self.history_buffer)
            # ── Atualiza BrancoDetector com o roll mais recente ────
            if res["items"]:
                ultima = res["items"][0]   # item mais recente (lista veio reversa)
                roll_atual = ultima.get("value", 0)
                cor_atual  = ultima.get("color", "?")
                _branco_detector.atualizar_roll(cor_atual, roll_atual)

                # ── BrancoHistorico: registra toda rodada ──────────
                _branco_hist.registrar_rodada(cor_atual, roll_atual)
                # ── BrancoStats: registra toda rodada ──────────────
                _branco_stats.registrar(cor_atual, roll_atual)

                # ── Atualiza NumeroStats ───────────────────────────
                if _NUMERO_STATS_DISPONIVEL:
                    alertas_num = _numero_stats.registrar_rodada(roll_atual)
                    alertas_grp = _grupo_seco.registrar_rodada(roll_atual)
                    self._alertas_numero_pendentes = (
                        getattr(self, '_alertas_numero_pendentes', []) +
                        alertas_num +
                        [{"tipo": "grupo", **a} for a in alertas_grp]
                    )
                    # ── Atualiza SequenciaStats ────────────────────
                    try:
                        from numero_stats import _sequencia_stats
                        _sequencia_stats.registrar(cor_atual)
                    except Exception:
                        pass

                # ── Registra no NumeroHoraFavorita ─────────────────
                _numero_hora.registrar(ultima.get("value", 0))
            # ── Atualiza VermelhoEngine com última cor real ─────────
            if self.vermelho_integrador:
                last_vp = next((c for c in reversed(self.history_buffer)
                                if c in ("V", "P")), None)
                if last_vp:
                    self.vermelho_integrador.registrar_resultado(
                        last_vp, self.history_buffer)

            _seen_this_round: set = set()

            for learner, lista, patterns_attr, label in [
                (self.auto_learner_a, "A", "patterns_a", "🅰️"),
                (self.auto_learner_b, "B", "patterns_b", "🅱️"),
                (self.auto_learner_c, "C", "patterns_c", "🏅"),
                (self.auto_learner_d, "D", "patterns_d", "📂"),
            ]:
                learner.discover(self.history_buffer, global_seen=_seen_this_round)
                promoted, removed = learner.update(self.history_buffer)

                if self.global_round % 50 == 0:
                    n = learner.cleanup_hopeless()
                    if n > 0:
                        asyncio.create_task(self._enqueue(
                            f"🧹 <b>Limpeza VP [{lista}]</b>\n"
                            f"🗑️ {n} candidatos removidos\n"
                            f"📊 Restam: {len(learner.candidates)} em teste"
                        ))

                for cand in promoted:
                    emoji   = COLOR_LETTER_TO_ENTRY_EMOJI.get(cand.prediction, "❓")
                    pat_str = " → ".join(
                        COLOR_LETTER_TO_EMOJI.get(str(c), str(c)) for c in cand.pattern)
                    asyncio.create_task(self._enqueue(
                        f"🧠 <b>NOVO PADRÃO VP ATIVADO! {label}</b>\n\n"
                        f"📋 {pat_str} → {emoji}\n"
                        f"✅ {cand.wins}W em {cand.total} testes "
                        f"(<b>{cand.accuracy:.1f}%</b>)\n"
                        f"📏 Tamanho: <b>{len(cand.pattern)}</b> | "
                        f"Critério: ≥11 testes / ≥90%\n"
                        f"🎯 Adicionado automaticamente!"
                    ))
                    setattr(self, patterns_attr,
                            self._load_patterns(learner.sequencias_path))

        # ── Confirmador pós-sinal: coleta cores VP após o sinal ─────
        if self._confirma_ativo and res and "items" in res:
            # Pega a cor mais recente da rodada que acabou de completar
            _ultima_cor_vp = next(
                (i["color"] for i in res["items"] if i["color"] in ("V", "P")), None
            )
            if _ultima_cor_vp:
                self._confirma_buffer.append(_ultima_cor_vp)
                _cnt_pred  = self._confirma_buffer.count(self._confirma_pred)
                _cnt_total = len(self._confirma_buffer)
                _ce        = {"V": "🔴", "P": "⚫"}
                _seq_str   = " ".join(_ce.get(c, c) for c in self._confirma_buffer)

                log.debug(
                    f"🔍 Confirmador [{self._confirma_pat}→{self._confirma_pred}] "
                    f"| rodada {_cnt_total}/{self._confirma_max} "
                    f"| {_ce.get(self._confirma_pred,'?')} {_cnt_pred}/{self._confirma_min}"
                )

                # ── Confirmado: ≥3 da cor predita nas últimas _confirma_max rodadas ──
                if _cnt_pred >= self._confirma_min:
                    _perc = round(_cnt_pred / _cnt_total * 100)
                    _msg_confirm = (
                        f"✅✅ <b>PADRÃO CONFIRMADO!</b>\n"
                        f"🏷️ <b>[{self._confirma_nome}]</b>  "
                        f"{_ce.get(self._confirma_pred,'?')} {self._confirma_pred}\n"
                        f"{'─' * 20}\n"
                        f"📊 Sequência pós-sinal:\n"
                        f"   {_seq_str}\n"
                        f"🎯 <b>{_cnt_pred}x {self._confirma_pred}</b> em "
                        f"{_cnt_total} rodadas  ({_perc}%)\n"
                        f"⚡ <i>Próxima entrada: fique atento ao padrão!</i>"
                    )
                    asyncio.create_task(self._send_async(_msg_confirm))
                    log.info(
                        f"✅ Confirmador CONFIRMADO | {self._confirma_pat}→{self._confirma_pred} "
                        f"| {_cnt_pred}x em {_cnt_total} rodadas"
                    )
                    self._confirma_ativo  = False
                    self._confirma_buffer = []

                # ── Janela esgotada sem confirmar ─────────────────────────
                elif _cnt_total >= self._confirma_max:
                    _msg_nconf = (
                        f"⚠️ <b>Padrão NÃO confirmado</b>\n"
                        f"🏷️ <b>[{self._confirma_nome}]</b>  "
                        f"{_ce.get(self._confirma_pred,'?')} {self._confirma_pred}\n"
                        f"{'─' * 20}\n"
                        f"📊 Sequência pós-sinal: {_seq_str}\n"
                        f"❌ Apenas <b>{_cnt_pred}x {self._confirma_pred}</b> "
                        f"em {_cnt_total} rodadas  "
                        f"(precisava de {self._confirma_min})\n"
                        f"<i>Mercado não confirmou o padrão desta vez.</i>"
                    )
                    asyncio.create_task(self._send_async(_msg_nconf))
                    log.info(
                        f"❌ Confirmador NÃO confirmado | {self._confirma_pat}→{self._confirma_pred} "
                        f"| {_cnt_pred}x em {_cnt_total} rodadas"
                    )
                    self._confirma_ativo  = False
                    self._confirma_buffer = []

        agora = time.time()
        if agora - self.last_matrix_time >= 300:
            matriz_msg = await self.build_matrix_msg()
            if matriz_msg:
                if self.last_matrix_msg_id:
                    try:
                        await self._edit_async(self.last_matrix_msg_id, matriz_msg)
                    except Exception:
                        self.last_matrix_msg_id = await self._send_async(matriz_msg)
                else:
                    self.last_matrix_msg_id = await self._send_async(matriz_msg)
                self.last_matrix_time = agora

    def _check_loss_protection(self) -> None:
        """Proteção de loss streak DESATIVADA — bot roda contínuo sem pausa automática."""
        # Pausa automática por losses consecutivos removida.
        # O bot continua operando independente de sequência de losses.
        pass

    def _winrate_hora_global(self, hora: str) -> tuple:
        """
        Calcula o winrate GLOBAL de todos os padrões juntos para uma hora.
        Retorna (winrate, total_amostras).
        Usado pelo Filtro 1 (Hora Quente/Fria).
        """
        total_w = 0
        total_t = 0
        for rec in self.pattern_records.values():
            total_w += rec.hour_wins.get(hora, 0)
            total_t += rec.hour_total.get(hora, 0)
        wr = total_w / total_t if total_t > 0 else 0.0
        return round(wr, 4), total_t

    def _freq_recente_padrao(self, pattern: list, prediction: str, janela: int) -> int:
        """
        Conta quantas vezes o padrão+predição apareceu nas últimas N rodadas VP.
        Usado pelo Filtro 4 (Frequência Recente).
        """
        vp = [c for c in self.history_buffer if c in ("V", "P")][-janela:]
        n  = len(pattern) + 1  # padrão + predição
        padrao_completo = list(pattern) + [prediction]
        count = 0
        for i in range(len(vp) - n + 1):
            if vp[i:i+n] == padrao_completo:
                count += 1
        return count

    def _seq_atual_pct_seca(self) -> int:
        """
        Verifica se a sequência das últimas 4 cores VP está em máxima seca.
        Retorna o % do recorde da sequência atual (0-100+).
        Usado pelo Filtro 3 (Sequência Atual Seca).
        """
        try:
            from numero_stats import _sequencia_stats
            vp = [c for c in self.history_buffer if c in ("V", "P")]
            if len(vp) < 4:
                return 0
            seq4 = vp[-4:]
            mx, seco, _ = _sequencia_stats._calcular(seq4)
            if mx == 0:
                return 0
            return int(seco / max(1, mx) * 100)
        except Exception:
            return 0

    def _taxa_loss_recente(self, minutos: int = 30) -> float:
        recentes = self.stats.last_results[-6:]
        if not recentes:
            return 0.0
        return recentes.count("❌") / len(recentes)

    async def _verificar_e_enviar_sinal(self) -> None:
        # ── GUARD 0: bloqueia 1 sinal após 2 losses consecutivos ──
        if self._bloqueia_proximo_sinal:
            self._bloqueia_proximo_sinal = False  # libera no próximo ciclo
            log.info("🛡️ SINAL BLOQUEADO — aguardando 1 rodada limpa após 2 losses")
            return

        # ── GUARD 1: bot pausado ou aposta já ativa ───────────────
        if not self.running or self.bet.active:
            return

        # ── GUARD 2: intervalo mínimo entre sinais (anti-duplo) ───
        # Se um sinal foi enviado há menos de _min_signal_interval segundos,
        # descarta silenciosamente — protege contra re-entrada imediata.
        agora_ts = time.time()
        if agora_ts - self._last_signal_ts < self._min_signal_interval:
            log.debug(
                f"⏱️ Intervalo mínimo não atingido "
                f"({agora_ts - self._last_signal_ts:.1f}s < {self._min_signal_interval}s) — ignorado"
            )
            return

        # ── Proteção de cold-start ────────────────────────────────
        if self.global_round < COLDSTART_MIN_RODADAS:
            log.info(
                f"⏳ Cold-start: {self.global_round}/{COLDSTART_MIN_RODADAS} rodadas "
                f"— aguardando calibração dos engines"
            )
            return


        res = await self.get_recent_cached()
        if res and "items" in res:
            colors              = [i["color"] for i in reversed(res["items"])]
            self.history_buffer = colors[-500:]
            self.markov.feed(self.history_buffer)

            # ── Minerador em Tempo Real ─────────────────────────
            if MINER_RT_ATIVO:
                self._rt_rodadas_desde_mine += 1
                if self._rt_rodadas_desde_mine >= MINER_RT_A_CADA_RODADAS:
                    self._rt_rodadas_desde_mine = 0
                    self._minerar_tempo_real()

        em_modo_conservador = self.global_round < self.modo_conservador_ate

        motor_result  = _motor_decisao.analisar(self.history_buffer)
        regime_line   = self.regime.linha_status()

        match = await self.find_pattern()

        if match:
            pattern, prediction, source, confirmadores = match
            key_block = (tuple(pattern), prediction)
            ks_block  = PatternNameRegistry._key_str(key_block)
            if (self.pattern_loss_until.get(ks_block, 0) - time.time()) > 0:
                mins = int((self.pattern_loss_until[ks_block] - time.time()) // 60) + 1
                log.info(f"🚫 LOSS-BLOCK 10min | {pattern}→{prediction} | {mins}min restantes")
                match = None

        # DESATIVADO: Filtro de Regime removido — todos os padrões passam
        # if match:
        #     regime_ok, regime_motivo = self.regime.filtra_padrao(pattern, prediction)
        #     if not regime_ok: match = None

        # ── FILTRO EV mínimo ──────────────────────────────────────────
        if match:
            pattern, prediction, source, confirmadores = match
            key_ev  = (tuple(pattern), prediction)
            ks_ev   = PatternNameRegistry._key_str(key_ev)
            rec_ev  = self.pattern_records.get(ks_ev)
            if rec_ev and rec_ev.total >= 5:
                # Calcula EV real do padrão usando dados acumulados
                p_win = rec_ev.accuracy / 100.0
                ev_real = (p_win * 1.0) - ((1 - p_win) * 1.0)
                if ev_real < EV_MINIMO_SINAL:
                    log.debug(
                        f"📉 EV baixo [{PatternNameRegistry._map.get(ks_ev,'?')}] "
                        f"EV={ev_real:.3f} < {EV_MINIMO_SINAL} — descartado"
                    )
                    match = None

        # ── CATEGORIA DO SINAL — exibe a categoria atual ─────────────
        # Não bloqueia por categoria — apenas registra e exibe
        if match:
            pattern, prediction, source, confirmadores = match
            key_cat = (tuple(pattern), prediction)
            ks_cat  = PatternNameRegistry._key_str(key_cat)
            nome_cat = self.pattern_names._map.get(ks_cat, "?")
            rec_cat  = self.pattern_records.get(ks_cat)
            wr_str   = f"{rec_cat.accuracy:.1f}%" if rec_cat and rec_cat.total >= 3 else "novo"
            cat_em   = self._cat_emoji(self._cat_atual)
            cat_lbl  = self._cat_label(self._cat_atual)
            log.info(
                f"{cat_em} SINAL CAT{self._cat_atual} {cat_lbl} | "
                f"[{nome_cat}] WR={wr_str} | "
                f"{self._cat_losses_seguidos} loss(es) consecutivo(s)"
            )

        if match:
            pattern, prediction, source, confirmadores = match
            listas_map = {
                "A": self.patterns_a, "B": self.patterns_b,
                "C": self.patterns_c, "D": self.patterns_d,
            }
            listas_com_match = sum(
                1 for lst in listas_map.values()
                if any(p[0] == pattern and p[1] == prediction for p in lst)
            )
            if listas_com_match < CONSENSO_MIN_LISTAS:
                log.info(
                    f"🔗 CONSENSO INSUFICIENTE | {pattern}→{prediction} | "
                    f"{listas_com_match}/{CONSENSO_MIN_LISTAS} listas — descartando"
                )
                match = None

        if match:
            pattern, prediction, source, confirmadores = match
            probs_mk = self.markov.predict(self.history_buffer)
            if probs_mk:
                cor_oposta  = "P" if prediction == "V" else "V"
                conf_oposta = probs_mk.get(cor_oposta, 0.0)
                if conf_oposta >= MARKOV_CANCEL_CONF:
                    log.info(
                        f"🧮 MARKOV CANCELOU | sinal {prediction} bloqueado | "
                        f"Markov aponta {cor_oposta} com {conf_oposta:.0%}"
                    )
                    match = None

        # ── Filtro 1: Entropia de Shannon ─────────────────────────
        if match:
            deve_bloquear_ent, entropia_val = self.entropia_guard.deve_bloquear(
                self.history_buffer)
            if deve_bloquear_ent:
                log.info(
                    f"🎲 ENTROPIA BLOQUEOU | H={entropia_val:.3f} > "
                    f"{ENTROPIA_HASH_LIMIAR} | mercado caótico"
                )
                match = None

        # ── Filtro 2: Autocorrelação de Pearson ───────────────────
        if match:
            pattern, prediction, source, confirmadores = match
            deve_bloquear_ac, corr_val = self.autocorr_pearson.deve_bloquear(
                self.history_buffer, pattern, prediction)
            if deve_bloquear_ac:
                log.info(
                    f"📐 AUTOCORR BLOQUEOU | r={corr_val:+.3f} < "
                    f"{AUTOCORR_LIMIAR} | padrão divergente do momento"
                )
                match = None

        # ── Filtro 3: Bias pós-branco ─────────────────────────────
        if match:
            pattern, prediction, source, confirmadores = match
            bias_status, bias_motivo = self.bias_pos_branco.avaliar_sinal(prediction)
            if bias_status == "bloqueia":
                log.info(f"⚪ BIAS PÓS-BRANCO BLOQUEOU | {bias_motivo}")
                match = None

        if match:
            pattern, prediction, source, confirmadores = match
            key_h = (tuple(pattern), prediction)
            ks_h  = PatternNameRegistry._key_str(key_h)
            rec_h = self.pattern_records.get(ks_h)
            if rec_h:
                hora_atual = datetime.now().strftime("%H")
                total_h    = rec_h.hour_total.get(hora_atual, 0)
                wins_h     = rec_h.hour_wins.get(hora_atual, 0)
                if total_h >= HORA_BLOCK_MIN_AMOSTRAS:
                    wr_h = wins_h / total_h
                    if wr_h < HORA_BLOCK_WINRATE_MIN:
                        log.info(
                            f"🕐 HORA BLOQUEADA | {hora_atual}h | "
                            f"winrate {wr_h:.0%} < {HORA_BLOCK_WINRATE_MIN:.0%} | {total_h} amostras"
                        )
                        match = None

        # ── FILTRO EXTRA 1: Hora Quente/Fria (global) ─────────────
        # Bloqueia quando o winrate GLOBAL de todos os padrões nessa hora
        # está abaixo do mínimo — independente do padrão individual.
        if match:
            hora_agora = datetime.now().strftime("%H")
            wr_global, total_global = self._winrate_hora_global(hora_agora)
            if total_global >= HORA_QUENTE_MIN_AMOSTRAS and wr_global < HORA_QUENTE_MIN_WR:
                pattern, prediction, source, confirmadores = match
                log.info(
                    f"🌡️ HORA FRIA BLOQUEOU | {hora_agora}h | "
                    f"WR global={wr_global:.0%} < {HORA_QUENTE_MIN_WR:.0%} | {total_global} ent"
                )
                match = None

        # ── FILTRO EXTRA 2: Streak de Loss do Padrão ──────────────
        # Bloqueia padrão que já errou >= STREAK_LOSS_BLOCK vezes seguidas.
        # Padrão em sequência de loss → em período ruim → pula.
        if match:
            pattern, prediction, source, confirmadores = match
            key_sl = (tuple(pattern), prediction)
            ks_sl  = PatternNameRegistry._key_str(key_sl)
            rec_sl = self.pattern_records.get(ks_sl)
            pass  # STREAK LOSS BLOCK desativado

        # ── FILTRO EXTRA 3: Sequência Atual em Máxima Seca ────────
        # Se a sequência das últimas 4 cores está em máxima histórica seca
        # → mercado em estado incomum → penaliza score (aplicado adiante).
        # (não bloqueia, só ajusta o score mínimo para ser mais exigente)
        _pct_seq_seca = self._seq_atual_pct_seca() if match else 0

        # ── FILTRO EXTRA 5: Double Confirmation Padrão + Regime ───
        # Só entra quando predição do padrão e regime apontam mesma direção.
        if match and DOUBLE_CONF_ATIVO:
            pattern, prediction, source, confirmadores = match
            regime_atual   = self.regime.regime
            regime_conf    = self.regime.confianca
            regime_dom     = self.regime.dominante

            if regime_conf >= DOUBLE_CONF_REGIME_MIN_CONF:
                bloqueado_dc = False
                motivo_dc    = ""

                if regime_atual == "trending":
                    # TRENDING: só entra na direção da tendência
                    if regime_dom and prediction != regime_dom:
                        bloqueado_dc = True
                        motivo_dc = (
                            f"TRENDING {regime_conf:.0%} favorece "
                            f"{COLOR_LETTER_TO_EMOJI.get(regime_dom,'?')} | "
                            f"padrão prevê {COLOR_LETTER_TO_EMOJI.get(prediction,'?')}"
                        )
                elif regime_atual == "alternating":
                    # ALTERNATING: só entra na cor oposta à última
                    vp_rec = [c for c in self.history_buffer if c in ("V","P")]
                    ultima_cor = vp_rec[-1] if vp_rec else None
                    cor_esperada = "P" if ultima_cor == "V" else "V"
                    if ultima_cor and prediction != cor_esperada:
                        bloqueado_dc = True
                        motivo_dc = (
                            f"ALTERNATING {regime_conf:.0%} espera "
                            f"{COLOR_LETTER_TO_EMOJI.get(cor_esperada,'?')} | "
                            f"padrão prevê {COLOR_LETTER_TO_EMOJI.get(prediction,'?')}"
                        )

                if bloqueado_dc:
                    log.info(f"🔀 DOUBLE CONF BLOQUEOU | {motivo_dc}")
                    match = None

        if match and em_modo_conservador:
            pattern, prediction, source, confirmadores = match
            key_c = (tuple(pattern), prediction)
            ks_c  = PatternNameRegistry._key_str(key_c)
            rec_c = self.pattern_records.get(ks_c)
            if rec_c and rec_c.total >= 3 and rec_c.accuracy < CONSERVADOR_ACC_DIA_MIN:
                log.info(
                    f"🛡️ CONSERVADOR BLOQUEOU | {pattern}→{prediction} | "
                    f"accuracy {rec_c.accuracy:.0f}% < {CONSERVADOR_ACC_DIA_MIN:.0f}%"
                )
                match = None

        if match:
            pattern, prediction, source, confirmadores = match

            if self.anomaly.is_paused(self.global_round):
                return
            is_anomaly, anomaly_type, _ = self.anomaly.analyze(
                self.history_buffer, self.stats.last_results, self.global_round)
            if is_anomaly:
                self.anomaly.pause(self.global_round, anomaly_type)
                asyncio.create_task(self._send_async(
                    f"⚠️ <b>ANOMALIA VP — SINAIS PAUSADOS</b>\n\n"
                    f"📊 Tipo: <b>{anomaly_type}</b>\n"
                    f"⏸️ Aguardando <b>{AnomalyDetector.PAUSE_ROUNDS} giros</b>"
                ))
                return

            tendencia   = await self._tendencia_mercado_vp()
            markov_line = self.markov.summary_str(self.history_buffer, prediction)
            rsi_result  = _rsi_ind.calculate(self.history_buffer, prediction)
            rsi_line    = rsi_result["linha"]

            # ── Linhas de status dos novos filtros ────────────────
            entropia_line = self.entropia_guard.linha_status(self.history_buffer)
            corr_val      = self.autocorr_pearson.calcular(self.history_buffer, pattern, prediction)
            autocorr_line = self.autocorr_pearson.linha_status(corr_val)
            bias_line     = self.bias_pos_branco.linha_status()

            key = (tuple(pattern), prediction)
            ks  = PatternNameRegistry._key_str(key)
            if ks not in self.pattern_records:
                self.pattern_records[ks] = PatternRecord()
            self.pattern_records[ks].register_appearance(self.global_round)

            # ── Cálculos internos (filtros — sem exibição no sinal) ──────────
            hora_result  = _filtro_hora.avaliar(self.pattern_records, ks)
            peso_result  = _peso_lista.avaliar(self.ab)

            rec_score   = self.pattern_records.get(ks)
            wr_padrao   = rec_score.accuracy if rec_score and rec_score.total >= 3 else 50.0
            streak_sc   = rec_score.current_win_streak if rec_score else 0
            total_ent   = rec_score.total if rec_score else 0
            entropia_sc = self.anomaly._entropy(self.history_buffer)
            _, markov_conf, _ = self.markov.confirm_signal(self.history_buffer, prediction)

            # ── FILTRO EXTRA 4: Frequência Recente do Padrão ──────
            # Bônus se apareceu >= 3x nas últimas 50 rodadas (fase quente)
            # Penalidade se apareceu 0x (fase seca incomum)
            freq_recente  = self._freq_recente_padrao(pattern, prediction, FREQ_RECENTE_JANELA)
            bonus_freq    = 0
            if freq_recente >= FREQ_RECENTE_QUENTE:
                bonus_freq = FREQ_RECENTE_BONUS
                log.info(f"🔥 FREQ QUENTE | {pattern}→{prediction} | {freq_recente}x nas últimas {FREQ_RECENTE_JANELA} rod | +{bonus_freq} score")
            elif freq_recente == FREQ_RECENTE_SECO and total_ent >= 5:
                bonus_freq = -FREQ_RECENTE_PENALIDADE
                log.info(f"🧊 FREQ SECO | {pattern}→{prediction} | 0x nas últimas {FREQ_RECENTE_JANELA} rod | {bonus_freq} score")

            score_result = _score_ind.calcular(
                winrate=wr_padrao, n_conf=len(confirmadores), markov=markov_conf,
                rsi_alerta=False, bonus_hora=hora_result["score_bonus"],
                streak=streak_sc, entropia=entropia_sc, total_ent=total_ent,
                bonus_regime=self.regime.score_bonus() + bonus_freq,
            )

            # ── FILTRO EXTRA 3: Sequência Atual em Máxima Seca ────
            # Se a sequência atual das últimas 4 cores está em máxima seca
            # → exige score maior (mercado em estado incomum)
            if _pct_seq_seca >= SEQ_SECA_PCT_ALERTA:
                score_result["score"] = max(0, score_result["score"] - SEQ_SECA_SCORE_PENALIDADE)
                log.info(
                    f"🧊 SEQ SECA PENALIDADE | {_pct_seq_seca}% do recorde | "
                    f"score ajustado para {score_result['score']}"
                )

            rec_sm         = self.pattern_records.get(ks)
            eh_padrao_novo = (rec_sm is None or rec_sm.total == 0)

            if score_result["score"] < SCORE_ABSOLUTO_MIN:
                log.info(f"🚫 SCORE_ABSOLUTO bloqueou | {pattern}->{prediction} | score {score_result['score']}")
                return

            if self.regime.regime == "chaotic" and score_result["score"] < CHAOTIC_SCORE_MIN:
                log.info(f"🌀 CHAOTIC_SCORE bloqueou | {pattern}->{prediction} | score {score_result['score']}")
                return

            if not eh_padrao_novo:
                score_ind = rec_sm.score_minimo_individual
                if em_modo_conservador:
                    score_ind = max(score_ind, CONSERVADOR_SCORE_MIN)
                score_ind = self.regime.score_minimo_override(score_ind)
                motor_discorda_ativo = (
                    motor_result and
                    not motor_result.get("indeciso", True) and
                    motor_result.get("decisao") != prediction
                )
                if motor_discorda_ativo and score_result["score"] < score_ind:
                    log.info(f"VP: {pattern}->{prediction} | score {score_result['score']} < {score_ind} — pulando")
                    return

            # ── VermelhoEngine: filtro interno ────────────────────
            # DESATIVADO: VermelhoEngine bloqueio removido — todos sinais V passam
            if False and self.vermelho_integrador and prediction == "V":
                ve_sinal = self.vermelho_integrador.analisar(
                    self.history_buffer,
                    score_padrao_classico=score_result["score"],
                    tem_padrao=True,
                )
                if not ve_sinal:
                    log.info("🔴 VermelhoEngine bloqueou sinal V — cancelando")
                    return

            # ── Kelly/EV/Bootstrap: apenas log interno ────────────
            nome_padrao  = self.pattern_names.get_name((tuple(pattern), prediction))
            _wins_p      = rec_score.wins  if rec_score else 0
            _total_p     = rec_score.total if rec_score else 0
            kelly_result = _kelly.calcular(_wins_p, _total_p,
                                           payout=COLOR_PAYOUT.get(prediction, 2.0),
                                           banca=self.gestor_banca.banca_atual)
            ev_result    = _ev_calc.calcular(_wins_p, _total_p,
                                             payout=COLOR_PAYOUT.get(prediction, 2.0),
                                             aposta=self.gestor_banca.get_valor_aposta(),
                                             pattern_nome=nome_padrao)
            _bootstrap.validar(_wins_p, _total_p, limiar=0.90, pattern_nome=nome_padrao)
            _branco_detector.checar_alerta()  # mantém estado interno

            # ── Limpa alertas pendentes ────────────────────────────
            if _NUMERO_STATS_DISPONIVEL:
                self._alertas_numero_pendentes = []

            # ── Registra timestamp (anti-duplo) ───────────────────
            self._last_signal_ts = time.time()

            gale_max_efetivo = self.cfg.max_gale if self.cfg.max_gale > 0 else (
                GALE_MAX_VERMELHO if prediction == "V" else GALE_MAX_PRETO
            )

            self.stats.total_signals += 1
            self.bet.active       = True
            self.bet.color        = prediction
            self.bet.pattern      = pattern
            self.bet.source       = source
            self.bet.gale_current = 0
            self.bet.gale_max     = gale_max_efetivo
            self.bet.origem       = "padrao"

            valor_apostado = 0.0
            if self.autobet and not self.autobet._pausado:
                valor_apostado = await self._executar_aposta(prediction)
            self.bet.valor_apostado = valor_apostado

            await self._send_entry_signal(
                prediction, source, confirmadores,
                score_dict=score_result,
                seq_bloco="",
                origem="padrao",
            )
            log.info(
                f"SINAL VP [PADRÃO] | {pattern}→{prediction} | lista={source} | "
                f"score={score_result['score']:.0f} | EV={ev_result['ev']:+.4f} | "
                f"kelly={kelly_result['fracao']*100:.1f}% | "
                f"regime={self.regime.regime} | autobet=R${valor_apostado:.2f}"
            )

        else:
            if em_modo_conservador:
                log.info("🛡️ MOTOR AUTÔNOMO DESATIVADO no modo conservador")
                return

            if motor_result["indeciso"] or motor_result["score"] < _motor_decisao.MIN_SCORE_AUTONOMO:
                return

            ind_ok = motor_result.get("detalhes", {}).get("indicadores_ok", 0)
            if ind_ok < MOTOR_MIN_INDICADORES_OK:
                log.info(
                    f"🤖 MOTOR: apenas {ind_ok}/{MOTOR_MIN_INDICADORES_OK} indicadores concordam — pulando"
                )
                return

            if self.cooldown.is_blocked():
                return

            if self.anomaly.is_paused(self.global_round):
                return
            is_anomaly, anomaly_type, _ = self.anomaly.analyze(
                self.history_buffer, self.stats.last_results, self.global_round)
            if is_anomaly:
                self.anomaly.pause(self.global_round, anomaly_type)
                asyncio.create_task(self._send_async(
                    f"⚠️ <b>ANOMALIA VP — SINAIS PAUSADOS</b>\n\n"
                    f"📊 Tipo: <b>{anomaly_type}</b>\n"
                    f"⏸️ Aguardando <b>{AnomalyDetector.PAUSE_ROUNDS} giros</b>"
                ))
                return

            decisao   = motor_result["decisao"]

            # ── Regime filtra sinal autônomo também ─────────────────
            vp_recente_check = [c for c in self.history_buffer if c in ("V","P")][-5:]
            pattern_check    = vp_recente_check if len(vp_recente_check) == 5 else []
            if pattern_check:
                regime_ok_auto, regime_motivo_auto = self.regime.filtra_padrao(pattern_check, decisao)
                if not regime_ok_auto:
                    pass  # DESATIVADO: regime bloqueio autônomo removido

            tendencia = await self._tendencia_mercado_vp()
            rsi_result = _rsi_ind.calculate(self.history_buffer, decisao)
            rsi_line   = rsi_result["linha"]

            probs_mk_auto = self.markov.predict(self.history_buffer)
            if probs_mk_auto:
                cor_op_auto  = "P" if decisao == "V" else "V"
                conf_op_auto = probs_mk_auto.get(cor_op_auto, 0.0)
                if conf_op_auto >= MARKOV_CANCEL_CONF:
                    log.info(
                        f"🧮 MARKOV CANCELOU [AUTÔNOMO] | {decisao} bloqueado | "
                        f"{cor_op_auto} com {conf_op_auto:.0%}"
                    )
                    return

            vp_recente   = [c for c in self.history_buffer if c in ("V","P")][-5:]
            pattern_auto = vp_recente if len(vp_recente) == 5 else []

            key_auto = (tuple(pattern_auto), decisao)
            ks_auto  = PatternNameRegistry._key_str(key_auto)
            if ks_auto not in self.pattern_records:
                self.pattern_records[ks_auto] = PatternRecord()
            self.pattern_records[ks_auto].register_appearance(self.global_round)

            hora_result  = _filtro_hora.avaliar(self.pattern_records, ks_auto)
            hora_line    = hora_result["linha"]
            peso_result  = _peso_lista.avaliar(self.ab)
            peso_line    = peso_result["linha"]
            markov_line  = self.markov.summary_str(self.history_buffer, decisao)

            # ── Linhas de status dos novos filtros (autônomo) ─────
            entropia_line_auto = self.entropia_guard.linha_status(self.history_buffer)
            corr_auto          = self.autocorr_pearson.calcular(
                self.history_buffer, pattern_auto, decisao)
            autocorr_line_auto = self.autocorr_pearson.linha_status(corr_auto)
            bias_line_auto     = self.bias_pos_branco.linha_status()

            # ── VermelhoEngine no motor autônomo (somente decisão V) ─
            if self.vermelho_integrador and decisao == "V":
                ve_auto = self.vermelho_integrador.analisar(
                    self.history_buffer,
                    score_padrao_classico=motor_result["score"],
                    tem_padrao=False,
                )
                if ve_auto:
                    peso_line = (
                        f"🔴 <b>VermelhoEngine</b> ✅  "
                        f"P(V)=<b>{ve_auto['p_v_posterior']:.3f}</b>  "
                        f"score=<b>{ve_auto['score_composto']:.0f}</b>  "
                        f"H={ve_auto['entropia_preditiva']:.3f}\n"
                    ) + peso_line
                else:
                    # DESATIVADO: sinal autônomo passa mesmo sem confirmação
                    pass  # log.info("🔴 VermelhoEngine bloqueou sinal autônomo V — cancelando")

            # ── Registra timestamp do sinal (anti-duplo) ──────────
            self._last_signal_ts = time.time()

            # ── Gale máx: nunca usa 0 (seria erro de config) ──────
            gale_max_efetivo_auto = self.cfg.max_gale if self.cfg.max_gale > 0 else (
                GALE_MAX_VERMELHO if decisao == "V" else GALE_MAX_PRETO
            )

            self.stats.total_signals += 1
            self.bet.active       = True
            self.bet.color        = decisao
            self.bet.pattern      = pattern_auto
            self.bet.source       = "AUTO"
            self.bet.gale_current = 0
            self.bet.gale_max     = gale_max_efetivo_auto
            self.bet.origem       = "autonomo"

            valor_apostado = 0.0
            if self.autobet and not self.autobet._pausado:
                valor_apostado = await self._executar_aposta(decisao)
            self.bet.valor_apostado = valor_apostado

            await self._send_entry_signal(
                decisao, "AUTO", [],
                score_dict=None,
                seq_bloco="",
                origem="autonomo",
            )
            log.info(
                f"SINAL VP [AUTÔNOMO] | decisao={decisao} | "
                f"confiança={motor_result['confianca']:.0%} | score={motor_result['score']} | "
                f"regime={self.regime.regime} | indicadores_ok={ind_ok}/{MOTOR_MIN_INDICADORES_OK} | "
                f"autobet=R${valor_apostado:.2f}"
            )

        if self.stats.total_signals > 0 and self.stats.total_signals % JANELA_SINAIS == 0:
            await self._send_relatorio_11()

    # ══════════════════════════════════════════════════════════════
    # HELPER: Cor dominante (padrão 5 ou 6 iguais)
    # ══════════════════════════════════════════════════════════════

    def _detectar_cor_dominante(self) -> Optional[str]:
        """
        Verifica se as últimas 5 ou 6 cores VP são todas iguais.
        Retorna a cor dominante ("V" ou "P") ou None.
        """
        vp = [c for c in self.history_buffer if c in ("V", "P")]
        for tam in (6, 5):
            if len(vp) >= tam:
                janela = vp[-tam:]
                if len(set(janela)) == 1:
                    return janela[0]
        return None

    def _verificar_cor_dominante_e_registrar(self, win: bool) -> None:
        """Registra win/loss no gestor de banca para padrão de cor dominante."""
        cor = self.cor_dom_ultimo
        if cor is None:
            return
        self.gestor_banca.registrar_cor_dominante(win)
        if win:
            self.cor_dom_wins += 1
        else:
            self.cor_dom_losses += 1
        self.cor_dom_ultimo = None

    async def _send_top10_padroes(self) -> None:
        """Top 10 padrões por assertividade — mín. 3 entradas."""
        confiaveis = {
            ks: rec for ks, rec in self.pattern_records.items()
            if rec.total >= 3
        }
        if not confiaveis:
            await self._send_async("🏆 <b>Top 10 Padrões</b> — aguardando dados (mín. 3 entradas).")
            return

        top10  = sorted(confiaveis.items(), key=lambda x: x[1].accuracy, reverse=True)[:10]
        CE     = {"V": "🔴", "P": "⚫"}
        medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

        linhas = []
        melhores_azul = []  # candidatos para bloco azul (WR >= 90%, >= 5 entradas)
        for pos, (ks, rec) in enumerate(top10):
            nome = self.pattern_names._map.get(ks, "?")
            try:
                parsed  = json.loads(ks)
                pat_str = "".join(CE.get(c, c) for c in parsed[0])
                pred    = CE.get(parsed[1], "?")
            except Exception:
                pat_str = "?"; pred = "?"

            # Barra de assertividade
            acc_int = int(rec.accuracy)
            barra   = "█" * (acc_int // 20) + "░" * (5 - acc_int // 20)

            # Streak atual
            if rec.current_win_streak >= 3:
                streak = f"  🔥{rec.current_win_streak}W"
            elif rec.current_loss_streak >= 1:
                streak = f"  💀{rec.current_loss_streak}L"
            else:
                streak = ""

            # Última vez usado
            ultima = f"  🕐{rec.last_used}" if rec.last_used else ""

            linhas.append(
                f"{medals[pos]} <b>[{nome}]</b>  "
                f"<code>{pat_str}→{pred}</code>\n"
                f"   <b>{rec.accuracy:.0f}%</b> <code>[{barra}]</code>  "
                f"{rec.wins}W/{rec.losses}L  ({rec.total} ent.)"
                f"{streak}{ultima}"
            )

            if rec.accuracy >= 90.0 and rec.total >= 5:
                melhores_azul.append((nome, pat_str, pred, rec))

        # Bloco azul — melhores para adicionar
        azul_bloco = ""
        if melhores_azul:
            azul_linhas = []
            for nome, pat_str, pred, rec in melhores_azul:
                streak_info = ""
                if rec.current_win_streak >= 3:
                    streak_info = f" 🔥{rec.current_win_streak}W seguidos"
                azul_linhas.append(
                    f"  ➕ <b>[{nome}]</b> {pat_str}→{pred}  "
                    f"<b>{rec.accuracy:.0f}%</b> ({rec.wins}W/{rec.losses}L)"
                    f"{streak_info}"
                )
            azul_bloco = (
                f"\n{'─' * 20}\n"
                f"🔵 <b>ADICIONA ESSES PADRÕES:</b>\n"
                + "\n".join(azul_linhas)
            )

        total_pads = len(confiaveis)
        await self._send_async(
            f"🏆 <b>Top 10 Padrões — Assertividade</b>\n"
            f"Base: <b>{total_pads}</b> padrões com ≥3 entradas\n"
            f"{'─' * 20}\n"
            + "\n".join(linhas) +
            f"\n{'─' * 20}"
            f"{azul_bloco}"
        )

    async def _send_cor_dominante_stats(self) -> None:
        """
        Envia estatísticas do padrão de quantidade de cores (5 ou 6 iguais).
        Mostra se é mais comum 5 ou 6 iguais e a assertividade de cada.
        """
        vp = [c for c in self.history_buffer if c in ("V", "P")]
        contagem5 = {"V": 0, "P": 0, "total": 0}
        contagem6 = {"V": 0, "P": 0, "total": 0}
        for i in range(len(vp)):
            for tam, cnt in ((5, contagem5), (6, contagem6)):
                if i >= tam:
                    janela = vp[i - tam: i]
                    if len(set(janela)) == 1:
                        cnt[janela[0]] += 1
                        cnt["total"]   += 1
        total_dom   = self.cor_dom_wins + self.cor_dom_losses
        wr_dom      = f"{self.cor_dom_wins/total_dom*100:.0f}%" if total_dom > 0 else "—"
        sinal_pnl   = "+" if self.gestor_banca.pnl_cor_dom >= 0 else ""
        await self._send_async(
            f"🎨 <b>Padrão Cor Dominante VP (5 ou 6 iguais)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"5️⃣ <b>Sequências de 5 iguais</b> detectadas:\n"
            f"   🔴 Vermelho: <b>{contagem5['V']}</b> | ⚫ Preto: <b>{contagem5['P']}</b>\n"
            f"6️⃣ <b>Sequências de 6 iguais</b> detectadas:\n"
            f"   🔴 Vermelho: <b>{contagem6['V']}</b> | ⚫ Preto: <b>{contagem6['P']}</b>\n\n"
            f"🎯 <b>Resultado ao entrar contra a sequência:</b>\n"
            f"   ✅ Wins: <b>{self.cor_dom_wins}</b>  ❌ Losses: <b>{self.cor_dom_losses}</b>  "
            f"📊 {wr_dom}\n"
            f"   💰 PnL: <b>{sinal_pnl}R${self.gestor_banca.pnl_cor_dom:.2f}</b> "
            f"(+10% win | -10% loss)\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

    # ── Relatório automático de 3 em 3 minutos ─────────────────────
    async def _send_relatorio_3min(self) -> None:
        """Relatório completo enviado a cada 3 minutos."""
        ativos      = {ks: rec for ks, rec in self.pattern_records.items() if rec.total >= 1}
        confiaveis  = {ks: rec for ks, rec in ativos.items() if rec.total >= 3}
        hora_atual  = datetime.now().strftime("%H:%M")

        # ── Top 5 padrões ─────────────────────────────────────────
        top5   = sorted(confiaveis.items(), key=lambda x: x[1].accuracy, reverse=True)[:5]
        CE     = {"V": "🔴", "P": "⚫"}
        medals = ["🥇","🥈","🥉","4️⃣","5️⃣"]
        top5_txt = ""
        melhores_para_adicionar = []  # padrões com WR >= 90% e >= 5 entradas
        for pos, (ks, rec) in enumerate(top5):
            nome = self.pattern_names._map.get(ks, "?")
            try:
                parsed  = json.loads(ks)
                pat_str = "".join(CE.get(c, c) for c in parsed[0])
                pred    = CE.get(parsed[1], "?")
            except Exception:
                pat_str = "?"; pred = "?"
            barra_acc = "█" * int(rec.accuracy // 20) + "░" * int(5 - int(rec.accuracy // 20))
            top5_txt += (
                f"  {medals[pos]} <b>[{nome}]</b> {pat_str}→{pred}  "
                f"<b>{rec.accuracy:.0f}%</b> <code>[{barra_acc}]</code> "
                f"<i>{rec.wins}W/{rec.losses}L</i>\n"
            )
            if rec.accuracy >= 90.0 and rec.total >= 5:
                melhores_para_adicionar.append((nome, pat_str, pred, rec))
        if not top5_txt:
            top5_txt = "  <i>Coletando dados...</i>\n"

        # ── Bloco azul: melhores padrões para adicionar ───────────
        azul_txt = ""
        if melhores_para_adicionar:
            azul_linhas = []
            for nome, pat_str, pred, rec in melhores_para_adicionar:
                streak_info = ""
                if rec.current_win_streak >= 3:
                    streak_info = f" 🔥{rec.current_win_streak}W seguidos"
                azul_linhas.append(
                    f"  ➕ <b>[{nome}]</b> {pat_str}→{pred}  "
                    f"<b>{rec.accuracy:.0f}%</b> ({rec.wins}W/{rec.losses}L)"
                    f"{streak_info}"
                )
            azul_txt = (
                f"{'─' * 20}\n"
                f"🔵 <b>ADICIONA ESSES PADRÕES:</b>\n"
                + "\n".join(azul_linhas) + "\n"
            )

        # ── Alerta de loss consecutivo ────────────────────────────
        alerta_consec = ""
        if self.stats.consecutive_losses >= 3:
            alerta_consec = (
                f"\n🚨 <b>ALERTA: {self.stats.consecutive_losses} losses consecutivos!</b> "
                f"Considere pausar.\n"
            )
        elif self.stats.consecutive_losses >= 2:
            alerta_consec = f"\n⚠️ <b>{self.stats.consecutive_losses} losses seguidos</b> — atenção.\n"

        # ── Métricas gerais ────────────────────────────────────────
        nivel_label  = self.minerador._nivel_atual["label"]
        melhor_nivel = self.minerador._melhor_nivel()
        total_dom    = self.cor_dom_wins + self.cor_dom_losses
        wr_dom       = f"{self.cor_dom_wins/total_dom*100:.0f}%" if total_dom > 0 else "—"
        losses_j     = self.stats.losses_na_janela()
        j_ok         = losses_j < MAX_LOSSES_NA_JANELA
        j_emoji      = "✅" if j_ok else f"⚠️ {losses_j}/{MAX_LOSSES_NA_JANELA}"
        taxa_30      = self._taxa_loss_recente(30)
        modo_txt     = "🛡️ CONSERVADOR" if self.global_round < self.modo_conservador_ate else "🟢 Normal"
        acc_txt      = f"{self.stats.accuracy:.1f}%"

        # ── Banca ─────────────────────────────────────────────────
        delta_banca = self.gestor_banca.banca_atual - self.gestor_banca.banca_inicial
        sinal_delta = "+" if delta_banca >= 0 else ""
        emoji_banca = "📈" if delta_banca >= 0 else "📉"

        # ── VermelhoEngine ────────────────────────────────────────
        ve_linha = ""
        if self.vermelho_integrador:
            ve_linha = f"{self.vermelho_integrador.engine.status_resumido()}\n"

        # ── Alerta hora favorita ──────────────────────────────────
        alerta_hora = _numero_hora.linha_alerta_hora_atual()
        alerta_hora_txt = f"{alerta_hora}\n" if alerta_hora else ""

        await self._send_async(
            f"📋 <b>RELATÓRIO  {hora_atual}</b>\n"
            f"{'─' * 20}\n"
            f"{self.stats.resumo_diario()}\n"
            f"{'─' * 20}\n"
            f"{alerta_consec}"
            f"{emoji_banca} Banca: <b>R$ {self.gestor_banca.banca_atual:.2f}</b>  "
            f"({sinal_delta}R$ {delta_banca:.2f})\n"
            f"✅ <b>{self.stats.wins}W</b>  ❌ <b>{self.stats.losses}L</b>  "
            f"📊 <b>{acc_txt}</b>  🎯 <b>{self.stats.total_signals}</b> sinais\n"
            f"{'─' * 20}\n"
            f"🏆 <b>Top 5 Padrões VP:</b>\n{top5_txt}"
            f"{azul_txt}"
            f"{'─' * 20}\n"
            f"{self.regime.linha_status()}\n"
            f"{self.entropia_guard.linha_status(self.history_buffer)}\n"
            f"{self.bias_pos_branco.linha_status()}\n"
            f"{_confusion.linha_status()}\n"
            f"💹 EV médio: <b>{_ev_calc.ev_medio_historico():+.4f}</b>\n"
            f"{alerta_hora_txt}"
            f"🚦 Janela: {j_emoji}  📉 Loss 30min: <b>{taxa_30:.0%}</b>\n"
            f"🔍 Minerador: <b>{nivel_label}</b> │ Melhor: <b>{melhor_nivel}</b>\n"
            f"🎮 Modo: <b>{modo_txt}</b>\n"
            f"{ve_linha}"
            f"🎨 Cor Dom: ✅{self.cor_dom_wins} ❌{self.cor_dom_losses} {wr_dom}\n"
        )

    async def _send_relatorio_11(self) -> None:
        ativos     = {ks: rec for ks, rec in self.pattern_records.items() if rec.total >= 1}
        confiaveis = {ks: rec for ks, rec in ativos.items() if rec.total >= 3}
        melhor_txt = "—"; pior_txt = "—"; culpado_txt = "—"

        if confiaveis:
            melhor_ks  = max(confiaveis, key=lambda k: confiaveis[k].accuracy)
            pior_ks    = min(confiaveis, key=lambda k: confiaveis[k].accuracy)
            melhor_rec = confiaveis[melhor_ks]
            pior_rec   = confiaveis[pior_ks]
            melhor_txt = (
                f"[{self.pattern_names._map.get(melhor_ks, '?')}] "
                f"{melhor_rec.accuracy:.0f}% ({melhor_rec.wins}W/{melhor_rec.losses}L)"
            )
            pior_txt = (
                f"[{self.pattern_names._map.get(pior_ks, '?')}] "
                f"{pior_rec.accuracy:.0f}% ({pior_rec.wins}W/{pior_rec.losses}L)"
            )

        if self.last_loss_pattern_ks:
            nome_c = self.pattern_names._map.get(self.last_loss_pattern_ks, "")
            rec_c  = self.pattern_records.get(self.last_loss_pattern_ks)
            if nome_c and rec_c:
                restantes = max(0, int((self.pattern_loss_until.get(self.last_loss_pattern_ks, 0) - time.time()) / 60))
                culpado_txt = f"[{nome_c}] — bloqueado {restantes}min restantes"

        losses_j = self.stats.losses_na_janela()
        j_ok     = losses_j < MAX_LOSSES_NA_JANELA
        janela_bloq_mins = max(0, int((self.janela_bloqueada_ate - time.time()) / 60))
        if janela_bloq_mins > 0:
            j_emoji = f"🔴 BLOQUEADO {janela_bloq_mins}min restantes"
        else:
            j_emoji  = "✅" if j_ok else f"⚠️ {losses_j}/{MAX_LOSSES_NA_JANELA}"
        modo_txt = "🛡️ CONSERVADOR" if self.global_round < self.modo_conservador_ate else "🟢 Normal"
        taxa_30  = self._taxa_loss_recente(30)

        autobet_bloco = ""
        if self.autobet:
            sinal_pnl = "+" if self.autobet._pnl_sessao >= 0 else ""
            modo = "🔵 DRY-RUN" if self.cfg.autobet.dry_run else "🟢 REAL"
            autobet_bloco = (
                f"\n🎰 <b>AutoBet {modo}</b>\n"
                f"   PnL sessão: <b>{sinal_pnl}R${self.autobet._pnl_sessao:.2f}</b>\n"
                f"   Nível atual: <b>{self.autobet._nivel_atual}</b> "
                f"| Próx: R${self.autobet._get_aposta_nivel():.2f}\n"
                f"   {'⛔ ' + self.autobet._motivo_pausa if self.autobet._pausado else '✅ Ativa'}\n"
            )

        await self._send_async(
            f"📋 <b>RELATÓRIO VP — {self.stats.total_signals} SINAIS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{self.stats.resumo_diario()}\n\n"
            f"💰 <b>Banca tracker:</b> R$ {self.gestor_banca.banca_atual:.2f}\n"
            f"✅ <b>{self.stats.wins}W</b>  ❌ <b>{self.stats.losses}L</b>  "
            f"📊 <b>{self.stats.accuracy:.0f}%</b>\n\n"
            f"🌊 <b>Regime atual:</b> {self.regime.linha_status()}\n"
            f"🚦 <b>Janela {JANELA_SINAIS} sinais:</b> {j_emoji} ({losses_j}/{MAX_LOSSES_NA_JANELA} losses)\n"
            f"📉 Taxa loss 30min: <b>{taxa_30:.0%}</b> "
            f"{'⚠️' if taxa_30 >= HORA_RUIM_LOSS_MAX else '✅'}\n"
            f"🎮 Modo atual: <b>{modo_txt}</b>\n"
            f"{autobet_bloco}\n"
            f"📏 Filtros ativos:\n"
            f"   🔒 Bloqueio pós-loss: <b>30min</b>\n"
            f"   🔗 Consenso obrigatório: <b>{CONSENSO_MIN_LISTAS} listas (A+B+C)</b>\n"
            f"   🧮 Markov cancelador: <b>≥{MARKOV_CANCEL_CONF:.0%}</b>\n"
            f"   🌊 Regime Switching: <b>ATIVO</b> (conf ≥{REGIME_CONF_MIN:.0%})\n"
            f"   🔒 Janela exclusão: <b>10 sinais</b> (loss → exclui)\n"
            f"   🕐 Hora mín. amostras: <b>{HORA_BLOCK_MIN_AMOSTRAS}</b> | winrate mín: <b>{HORA_BLOCK_WINRATE_MIN:.0%}</b>\n"
            f"   🎲 Entropia: <b>limiar {ENTROPIA_HASH_LIMIAR}</b> | janela {ENTROPIA_HASH_JANELA} rod.\n"
            f"   📐 Autocorr Pearson: <b>mín r={AUTOCORR_LIMIAR}</b> | janela {AUTOCORR_JANELA} rod.\n"
            f"   ⚪ Bias pós-branco: <b>{'ATIVO' if BIAS_POS_BRANCO_ATIVO else 'INATIVO'}</b> | {self.bias_pos_branco.linha_status()}\n"
            f"   📈 Score mínimo atual: <b>{self.score_minimo_atual}</b> "
            f"(override regime: <b>{self.regime.score_minimo_override(self.score_minimo_atual)}</b>)\n\n"
            f"🏆 Melhor padrão: <b>{melhor_txt}</b>\n"
            f"📉 Menor acc: <b>{pior_txt}</b>\n"
            f"🔒 Último loss: <b>{culpado_txt}</b>"
            f"━━━━━━━━━━━━━━━━━━"
        )


async def main() -> None:
    bot = BlazeBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nBot VP encerrado.")
    except Exception as e:
        log.critical(f"Erro crítico: {e}")
    finally:
        await bot.close()


if __name__ == "__main__":
    import sys, os

    # ── Proteção de instância única ───────────────────────────────
    LOCK_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "bot.lock")

    def _remover_lock():
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except Exception:
            pass

    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as _f:
                _pid = int(_f.read().strip())
            # Tenta verificar se o processo ainda existe
            try:
                import psutil
                ainda_vivo = psutil.pid_exists(_pid)
            except ImportError:
                # psutil não instalado — checa via os.kill(pid, 0)
                try:
                    os.kill(_pid, 0)
                    ainda_vivo = True
                except (OSError, ProcessLookupError):
                    ainda_vivo = False
            if ainda_vivo:
                print(
                    f"\n⚠️  Bot já está rodando (PID {_pid}).\n"
                    f"   Feche-o primeiro ou delete o arquivo 'bot.lock'.\n"
                )
                sys.exit(1)
            else:
                _remover_lock()  # processo morreu, limpa lock
        except Exception:
            _remover_lock()

    try:
        with open(LOCK_FILE, "w") as _f:
            _f.write(str(os.getpid()))
    except Exception:
        pass

    import atexit
    atexit.register(_remover_lock)

    try:
        asyncio.run(main())
    finally:
        _remover_lock()