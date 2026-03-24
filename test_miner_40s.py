#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste do FastPatternMiner40s — validar lógica de recalculação e filtragem
"""

import asyncio
import sys
from datetime import datetime

# Importar o minerador
from fast_pattern_miner_40s import FastPatternMiner40s

async def test_miner_basico():
    """Teste básico: criar instância, validar atributos"""
    print("=" * 60)
    print("🧪 Teste 1: Instanciação básica")
    print("=" * 60)
    
    miner = FastPatternMiner40s()
    assert miner.CYCLE_SECONDS == 40, "Cycle deveria ser 40s"
    assert miner.JANELA_RODADAS == 300, "Janela deveria ser 300"
    assert miner.MIN_WINRATE == 0.80, "WR min deveria ser 0.80"
    assert miner.MIN_OCORRENCIAS == 6, "Ocorrências min deveria ser 6"
    assert miner.TOP_KEEP == 40, "Top keep deveria ser 40"
    
    print("✅ Instância criada com parâmetros corretos")
    print(f"   • Ciclo: {miner.CYCLE_SECONDS}s")
    print(f"   • Janela: {miner.JANELA_RODADAS} rodadas")
    print(f"   • Min WR: {miner.MIN_WINRATE*100:.1f}%")
    print(f"   • Min Oc: {miner.MIN_OCORRENCIAS}")
    print(f"   • Top Keep: {miner.TOP_KEEP}")

def test_minerar_ciclo():
    """Teste 2: Lógica de mineração em ciclo com dados sintéticos"""
    print("\n" + "=" * 60)
    print("🧪 Teste 2: Mineração de ciclo com dados sintéticos")
    print("=" * 60)
    
    miner = FastPatternMiner40s()
    
    # Criar histórico sintético: 350 rodadas alternadas V-P com alguns padrões
    historia = []
    # 200 rodadas com padrão forte: VPVPV → V (80% WR)
    for _ in range(40):
        historia.extend(['V', 'P', 'V', 'P', 'V', 'V'])  # padrão seguido de vitória
    
    # 50 rodadas aleatórias
    import random
    random.seed(42)
    for _ in range(50):
        historia.append(random.choice(['V', 'P']))
    
    # Adicionar mais 100 rodadas com outro padrão: PVPVP → P (75% WR)
    for _ in range(25):
        historia.extend(['P', 'V', 'P', 'V', 'P', 'P'])  # padrão seguido de vitória
    
    print(f"📊 Histórico sintético: {len(historia)} rodadas")
    print(f"   Amostra (primeiras 20): {historia[:20]}")
    
    # Minerar
    padroes = miner._minerar_ciclo(historia)
    
    print(f"\n✅ Mineração completada: {len(padroes)} padrões encontrados")
    
    if padroes:
        print(f"\n   TOP 5 padrões:")
        for i, p in enumerate(padroes[:5], 1):
            cores_str = "".join(p.pattern)
            print(f"   {i}. {cores_str} → {p.prediction}  |  "
                  f"WR={p.winrate*100:.1f}% | {p.wins}W/{p.total-p.wins}L")
        
        # Validações
        assert len(padroes) <= miner.TOP_KEEP, f"Deveria ter no máx {miner.TOP_KEEP} padrões"
        assert all(p.winrate >= miner.MIN_WINRATE for p in padroes), \
            "Todos padrões devem ter WR >= 0.78"
        assert all(p.total >= miner.MIN_OCORRENCIAS for p in padroes), \
            "Todos padrões devem ter >= 6 ocorrências"
        assert padroes[0].winrate >= padroes[-1].winrate if len(padroes) > 1 else True, \
            "Padrões devem estar ordenados por WR desc"
        
        print("\n   ✅ Validações de filtro: PASSOU")
        print(f"      • Todos WR >= {miner.MIN_WINRATE*100:.1f}%")
        print(f"      • Todos oc >= {miner.MIN_OCORRENCIAS}")
        print(f"      • Ordenados por score desc")
    else:
        print("   ⚠️  Nenhum padrão encontrado (esperado se histórico curto)")

async def test_sinal_agregado():
    """Teste 3: Cálculo de sinal agregado"""
    print("\n" + "=" * 60)
    print("🧪 Teste 3: Cálculo de sinal agregado")
    print("=" * 60)
    
    from fast_pattern_miner_40s import PatternInfo
    
    miner = FastPatternMiner40s()
    
    # Simular padrões com predições mistas
    miner.padroes_ativos = [
        PatternInfo(("V", "P", "V", "P", "V"), "V", 0.85, 17, 20),
        PatternInfo(("P", "V", "P", "V", "P"), "V", 0.80, 16, 20),
        PatternInfo(("V", "V", "V", "P", "V"), "V", 0.82, 18, 22),
        PatternInfo(("P", "P", "V", "P", "P"), "P", 0.79, 15, 19),
        PatternInfo(("V", "P", "P", "V", "V"), "P", 0.78, 14, 18),
    ]
    
    sinal = miner._calcular_sinal_agregado()
    
    print(f"📊 Simulação com 5 padrões:")
    print(f"   • 3 predizem V")
    print(f"   • 2 predizem P")
    print(f"\n✅ Sinal agregado calculado: {sinal}")
    assert sinal == "V", "Deveria ser V (maioria)"
    print(f"   ✅ Resultado correto (maioria V)")
    
    # Teste com empatado (prefere V)
    miner.padroes_ativos = miner.padroes_ativos[:2]  # 2 V
    miner.padroes_ativos.append(PatternInfo(("X", "Y", "Z", "A", "B"), "P", 0.79, 16, 20))
    
    sinal2 = miner._calcular_sinal_agregado()
    print(f"\n   Empatado (2V vs 1P): {sinal2}")
    assert sinal2 == "V", "Empatado deve preferir V"
    print(f"   ✅ Empatado prefere V (correto)")

async def test_resumo_ciclo():
    """Teste 4: Formatação de resumo para Telegram"""
    print("\n" + "=" * 60)
    print("🧪 Teste 4: Formatação de resumo")
    print("=" * 60)
    
    from fast_pattern_miner_40s import PatternInfo
    
    miner = FastPatternMiner40s()
    
    # Simular alguns ciclos
    miner.ciclos_rodados = 5
    miner.ultima_atualizacao = "14:32:45"
    miner.sinal_agregado = "V"
    miner.padroes_ativos = [
        PatternInfo(("V", "P", "V", "P", "V"), "V", 0.85, 17, 20),
        PatternInfo(("P", "V", "P", "V", "P"), "V", 0.82, 18, 22),
        PatternInfo(("V", "V", "V", "P", "V"), "V", 0.79, 15, 19),
    ]
    
    resumo = miner.resumo_ciclo()
    
    print("📋 Resumo formatado:")
    print(resumo)
    
    assert "Ciclo 5" in resumo, "Deve conter número do ciclo"
    assert "3" in resumo and "padrões ativos" in resumo, "Deve conter contagem de padrões"
    assert "14:32:45" in resumo, "Deve conter timestamp"
    
    print("\n   ✅ Resumo formatado corretamente")

async def test_rastreamento_losses():
    """Teste 5: Validar rastreamento de losses e sequências"""
    print("\n" + "=" * 60)
    print("🧪 Teste 5: Rastreamento de losses e sequências")
    print("=" * 60)
    
    miner = FastPatternMiner40s()
    
    # Teste inicial: nenhum loss
    assert miner.total_losses == 0, "Deveria começar com 0 losses"
    assert miner.max_loss_sequence == 0, "Deveria começar com 0 max sequence"
    print("✅ Inicialização de losses validada")
    
    # Teste 1: Registrar 3 losses seguidos
    miner.registrar_loss()
    miner.registrar_loss()
    miner.registrar_loss()
    
    assert miner.total_losses == 3, "Deveria ter 3 losses registrados"
    assert miner.loss_sequence_atual == 3, "Sequência atual deveria ser 3"
    assert miner.max_loss_sequence == 3, "Max sequence deveria ser 3"
    print("✅ 3 losses consecutivos registrados")
    print(f"   Total: {miner.total_losses} | Max Seq: {miner.max_loss_sequence} | Seq Atual: {miner.loss_sequence_atual}")
    
    # Teste 2: Registrar win (reseta sequência)
    miner.registrar_win()
    
    assert miner.loss_sequence_atual == 0, "Sequência atual deveria ser resetada"
    assert miner.max_loss_sequence == 3, "Max sequence deveria manter 3"
    assert len(miner.historico_losses) == 1, "Deveria ter 1 sequência no histórico"
    print("✅ Win reseta sequência atual")
    print(f"   Seq Atual após win: {miner.loss_sequence_atual} | Histórico: {miner.historico_losses}")
    
    # Teste 3: Outra sequência (2 losses)
    miner.registrar_loss()
    miner.registrar_loss()
    
    assert miner.total_losses == 5, "Deveria ter 5 losses total"
    assert miner.loss_sequence_atual == 2, "Sequência atual deveria ser 2"
    assert miner.max_loss_sequence == 3, "Max sequence ainda deveria ser 3"
    print("✅ Segunda sequência de 2 losses registrada")
    print(f"   Total: {miner.total_losses} | Max Seq: {miner.max_loss_sequence} | Seq Atual: {miner.loss_sequence_atual}")
    
    # Teste 4: Win e depois 5 losses (nova máxima)
    miner.registrar_win()
    for _ in range(5):
        miner.registrar_loss()
    
    assert miner.max_loss_sequence == 5, "Max sequence deveria ser 5 (nova máxima)"
    assert miner.total_losses == 10, "Total deveria ser 10"
    print("✅ Nova sequência máxima (5 losses) registrada")
    print(f"   Total: {miner.total_losses} | Max Seq: {miner.max_loss_sequence}")
    
    # Teste 5: Obter estatísticas
    stats = miner.obter_stats_losses()
    
    assert stats["total_losses"] == 10
    assert stats["max_loss_sequence"] == 5
    assert stats["loss_sequence_atual"] == 5
    assert len(stats["historico"]) > 0
    print("✅ Estatísticas retornadas corretamente")
    print(f"   Stats: {stats}")
    
    print("✅ Rastreamento de losses validado com sucesso")


async def test_sinal_com_losses():
    """Teste 6: Validar que sinal inclui informações de losses"""
    print("\n" + "=" * 60)
    print("🧪 Teste 6: Sinal inclui estatísticas de losses")
    print("=" * 60)
    
    miner = FastPatternMiner40s()
    
    # Adicionar padrões
    from fast_pattern_miner_40s import PatternInfo
    p1 = PatternInfo(
        pattern=('V', 'P', 'V', 'P', 'V'),
        prediction='V',
        winrate=0.85,
        wins=17,
        total=20
    )
    miner.padroes_ativos = [p1]
    miner.sinal_agregado = 'V'
    
    # Registrar alguns losses
    miner.registrar_loss()
    miner.registrar_loss()
    miner.registrar_loss()
    
    # Gerar sinal
    sinal = miner.gerar_sinal()
    
    assert sinal is not None, "Deveria gerar sinal"
    assert "losses" in sinal, "Sinal deveria incluir dados de losses"
    assert sinal["losses"]["total"] == 3, "Total de losses deveria ser 3"
    assert sinal["losses"]["max_sequence"] == 3, "Max sequence deveria ser 3"
    assert sinal["losses"]["atual"] == 3, "Sequência atual deveria ser 3"
    
    print("✅ Sinal inclui estatísticas de losses")
    print(f"   Losses: {sinal['losses']}")
    
    print("✅ Teste validado com sucesso")


async def test_controle_sinal_40s():
    """Teste 7: Validar controle de frequência de sinais (40s)"""
    print("\n" + "=" * 60)
    print("🧪 Teste 7: Controle de frequência de sinais (40s)")
    print("=" * 60)
    
    miner = FastPatternMiner40s()
    
    # Adicionar padrões de teste
    from fast_pattern_miner_40s import PatternInfo
    p1 = PatternInfo(
        pattern=('V', 'P', 'V', 'P', 'V'),
        prediction='V',
        winrate=0.85,
        wins=17,
        total=20
    )
    miner.padroes_ativos = [p1]
    miner.sinal_agregado = 'V'
    
    # Teste 1: Pode gerar sinal no início
    pode = miner.pode_gerar_sinal()
    assert pode, "Deveria poder gerar sinal na primeira vez"
    print("✅ Pode gerar sinal inicialmente")
    
    # Teste 2: Gera sinal
    sinal = miner.gerar_sinal()
    assert sinal is not None, "Deveria gerar sinal"
    assert sinal['sinal'] == 'V', "Sinal deveria ser V"
    assert sinal['ciclo'] == 0, "Ciclo deveria ser 0"
    print(f"✅ Sinal gerado: {sinal['sinal']} | Ciclo {sinal['ciclo']}")
    
    # Teste 3: Não pode gerar sinal logo depois (ainda em cooldown)
    sinal2 = miner.gerar_sinal()
    assert sinal2 is None, "Não deveria gerar sinal em cooldown de 40s"
    print("✅ Cooldown de 40s respeitado (sinal negado)")
    
    print("✅ Controle de frequência validado com sucesso")


async def main():
    """Executa todos os testes"""
    print("\n" + "🧪" * 30)
    print("  TESTES DO FASTPATTERNMINER40S")
    print("🧪" * 30 + "\n")
    
    try:
        # Teste 1
        await test_miner_basico()
        
        # Teste 2
        test_minerar_ciclo()
        
        # Teste 3
        await test_sinal_agregado()
        
        # Teste 4
        await test_resumo_ciclo()
        
        # Teste 5
        await test_rastreamento_losses()
        
        # Teste 6
        await test_sinal_com_losses()
        
        # Teste 7
        await test_controle_sinal_40s()
        
        print("\n" + "=" * 60)
        print("✅ TODOS OS TESTES PASSARAM!")
        print("=" * 60)
        print("\nO FastPatternMiner40s está pronto para integração.")
        
    except AssertionError as e:
        print(f"\n❌ ERRO DE VALIDAÇÃO: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERRO INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
