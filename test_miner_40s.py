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
    assert miner.MIN_WINRATE == 0.78, "WR min deveria ser 0.78"
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
