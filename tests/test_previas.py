from pathlib import Path

import pytest

from oraculo.sistemas.generico.gerador import gerar_ficha, validar
from oraculo.sistemas.generico.modelo import SistemaLido, normalizar

PASTA = Path(__file__).parents[1] / "dados" / "publicos" / "previas"


@pytest.mark.parametrize("arquivo", ["dnd5e_srd51.json", "fm_v2_5_2.json"])
def test_previa_carrega_completa_e_gera_fichas_validas(arquivo):
    s = normalizar(SistemaLido.model_validate_json((PASTA / arquivo).read_text(encoding="utf-8")))
    opcoes = [o for e in s.etapas for o in e.opcoes]
    assert opcoes and all(o.detalhada for o in opcoes)
    assert s.ficha
    for seed in range(5):
        erros = [p for p in validar(s, gerar_ficha(s, seed=seed)) if p.gravidade == "erro"]
        assert erros == []
