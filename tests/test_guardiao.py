from oraculo.guardiao import sistemas_publicos, verificar

PUBLICOS = {"dnd5e"}


def test_dnd5e_srd_e_publico():
    assert "dnd5e" in sistemas_publicos()


def test_codigo_comum_passa():
    arquivos = ["src/oraculo/nucleo/ficha.py", "README.md", "dados/publicos/dnd5e/magias.parquet"]
    assert verificar(arquivos, PUBLICOS) == []


def test_bloqueia_livros():
    assert verificar(["livros/Livro do Jogador.pdf"], PUBLICOS)
    assert verificar(["qualquer/coisa.EPUB"], PUBLICOS)


def test_permite_fixture_aberta():
    assert verificar(["tests/fixtures/abertos/srd-5.1-trecho.pdf"], PUBLICOS) == []


def test_bloqueia_pasta_privada():
    assert verificar(["dados/privado/fm/tecnicas.json"], PUBLICOS)


def test_bloqueia_dados_publicos_de_sistema_sem_licenca():
    assert verificar(["dados/publicos/fm/tecnicas.parquet"], PUBLICOS)


def test_caminho_windows():
    assert verificar(["livros\\phb.pdf"], PUBLICOS)


def test_modelos_publicos_so_os_liberados():
    assert verificar(["dados/publicos/modelos/detector_rpg.json"], PUBLICOS) == []
    assert verificar(["dados/publicos/modelos/modelo_misterioso.json"], PUBLICOS)
