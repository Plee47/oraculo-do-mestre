"""Treino e avaliação leave-one-book-out com um corpus sintético pequeno."""

import pandas as pd
import pytest

from oraculo.leitor.detector import FEATURES, ModeloDetector
from oraculo.leitor.treino import (
    avaliar_leave_one_book_out,
    tabela_de_paginas,
    treinar_modelo_final,
)

RPG = (
    "Armor Class 15, Hit Points 30 (5d8 + 5). STR 16 (+3) DEX 12 (+1). Make a DC 13 saving "
    "throw. Your character adds the proficiency bonus to the attack roll and deals 1d8 damage. "
)
NAO = (
    "The river ran quietly past the old mill, and she said that the summer had been long. "
    "He walked home through the fields while the light faded over the distant hills. "
)


@pytest.fixture(scope="module")
def corpus() -> pd.DataFrame:
    linhas = []
    for livro, texto, rpg in [
        ("a", RPG, True),
        ("b", RPG, True),
        ("c", NAO, False),
        ("d", NAO, False),
    ]:
        for i in range(15):
            linhas.append(
                {
                    "fonte_id": livro,
                    "pagina": i,
                    "texto": texto * (3 + i % 3),
                    "rpg": rpg,
                    "categoria": "rpg" if rpg else "literatura",
                }
            )
    linhas.append({"fonte_id": "a", "pagina": 99, "texto": "capa", "rpg": True, "categoria": "rpg"})
    return tabela_de_paginas(pd.DataFrame(linhas))


def test_paginas_curtas_saem_da_tabela(corpus):
    assert (corpus["pagina"] != 99).all()
    assert set(FEATURES) <= set(corpus.columns)


@pytest.mark.parametrize("modelo", ["features", "tfidf"])
def test_leave_one_book_out(corpus, modelo):
    r = avaliar_leave_one_book_out(corpus, modelo)
    assert set(r.documentos["fonte_id"]) == {"a", "b", "c", "d"}
    assert len(r.paginas) == len(corpus)
    assert {"pagina_f1", "pagina_auc", "documento_acuracia", "documentos_errados"} <= set(
        r.metricas
    )
    assert r.metricas["documentos_errados"] == 0


def test_modelo_final_exportavel(corpus, tmp_path):
    m = treinar_modelo_final(corpus)
    assert set(m.coeficientes) == set(FEATURES)
    m.salvar(tmp_path / "d.json")
    assert ModeloDetector.carregar(tmp_path / "d.json").prob_pagina(RPG * 3) > 0.5
