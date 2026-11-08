"""Garante que /docs, /redoc e /openapi.json só ficam expostos em desenvolvimento.

Essas rotas não exigem autenticação e, em produção, vazam a estrutura completa
da API (incluindo schemas de rotas sensíveis como /funcionarios/criar e
/compras/autorizar/{compra_id}). Ver AMBIENTE em src/main.py.
"""
import importlib.util
import os

from fastapi.testclient import TestClient

import main

_SEM_VALOR_ANTERIOR = object()


def _montar_app(ambiente):
    """Recarrega o módulo main.py (direto do arquivo, sem depender de sys.path)
    com AMBIENTE setado (ou removido) e devolve o app resultante.

    Carrega via spec_from_file_location (apontando para o arquivo exato de
    `main.__file__`) em vez de importlib.reload/sys.path, para não arriscar
    resolver um main.py de outro diretório quando há mais de um checkout do
    projeto acessível (ex.: múltiplos worktrees). Também não mexe em
    sys.modules, então o `app` usado pelos outros testes não é afetado.
    """
    anterior = os.environ.get("AMBIENTE", _SEM_VALOR_ANTERIOR)
    if ambiente is None:
        os.environ.pop("AMBIENTE", None)
    else:
        os.environ["AMBIENTE"] = ambiente
    try:
        spec = importlib.util.spec_from_file_location("main_docs_exposure_test", main.__file__)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo.app
    finally:
        if anterior is _SEM_VALOR_ANTERIOR:
            os.environ.pop("AMBIENTE", None)
        else:
            os.environ["AMBIENTE"] = anterior


def test_docs_disponiveis_em_desenvolvimento_padrao():
    app = _montar_app(None)
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_desativadas_em_producao():
    app = _montar_app("producao")
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
