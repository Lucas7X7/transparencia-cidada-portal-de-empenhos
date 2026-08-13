from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.connectors import criar_conector, listar_portais
from app.services import relatorio, sincronizar

app = FastAPI(title="Portal de Transparência Cidadã", version="0.1.0")

_FRONT = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "frontend"


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/portais")
def portais():
    return [
        {"id": p.id, "nome": p.nome, "uf": p.uf, "esfera": p.esfera,
         "tipo": p.tipo, "url": p.url}
        for p in listar_portais()
    ]


@app.post("/api/sincronizar")
def api_sincronizar(
    portal_id: str = Query(...),
    ano: int = Query(2026),
    data_ini: str = Query(""),
    data_fim: str = Query(""),
    com_historico: bool = Query(True),
):
    try:
        return sincronizar.sincronizar(portal_id, ano, data_ini, data_fim, com_historico)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Falha ao acessar portal: {e}")


@app.get("/api/empenhos")
def api_buscar(
    portal_id: str = Query(...),
    termo: str = Query(""),
    favorecido: str = Query(""),
    cpf_cnpj: str = Query(""),
    unidade: str = Query(""),
    data_ini: str = Query(""),
    data_fim: str = Query(""),
    min_valor: float | None = Query(None),
    max_valor: float | None = Query(None),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(100, ge=1, le=1000),
    origem: str = Query("cache"),
):
    """Busca empenhos. Se origem=cache usa o banco local; se origem=portal consulta ao vivo.
    Portais estaduais (mt_estado) sempre consultam ao vivo."""
    portal_info = next((p for p in listar_portais() if p.id == portal_id), None)
    if portal_info is None:
        raise HTTPException(404, "Portal não encontrado")
    if portal_info.tipo == "mt_estado":
        origem = "portal"
    if origem == "portal":
        try:
            empenhos = _buscar_vivo(portal_id, termo, favorecido, cpf_cnpj,
                                    unidade, data_ini, data_fim)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise HTTPException(502, f"Falha ao acessar portal: {e}")
    else:
        empenhos = db.buscar(
            portal_id, termo=termo, favorecido=favorecido, cpf_cnpj=cpf_cnpj,
            unidade=unidade, data_ini=data_ini, data_fim=data_fim,
            min_valor=min_valor, max_valor=max_valor,
        )
    total = len(empenhos)
    inicio = (pagina - 1) * por_pagina
    fatia = empenhos[inicio:inicio + por_pagina]
    resumo = {
        "total": total,
        "total_empenhado": round(sum(e.empenhado for e in empenhos), 2),
        "total_liquidado": round(sum(e.liquidado for e in empenhos), 2),
        "total_pago": round(sum(e.pago for e in empenhos), 2),
        "total_favorecidos": len({e.favorecido for e in empenhos}),
    }
    return {
        "resumo": resumo,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "empenhos": [
            {
                "numeroAno": e.numeroAno, "dataEmpenho": e.dataEmpenho,
                "favorecido": e.favorecido, "cpfCnpj": e.cpfCnpj,
                "unidadeGestora": e.unidadeGestora,
                "unidadeOrcamentaria": e.unidadeOrcamentaria,
                "orgao": e.orgao, "elementoDespesa": e.elementoDespesa,
                "naturezaDespesa": e.naturezaDespesa, "fonteRecurso": e.fonteRecurso,
                "empenhado": e.empenhado, "liquidado": e.liquidado,
                "pago": e.pago, "historico": e.historico,
            }
            for e in fatia
        ],
    }


def _portal_tipo(portal_id: str) -> str:
    portal = next((p for p in listar_portais() if p.id == portal_id), None)
    if portal is None:
        raise HTTPException(404, "Portal não encontrado")
    return portal.tipo


def _buscar_vivo(portal_id: str, termo: str, favorecido: str, cpf_cnpj: str,
                 unidade: str, data_ini: str, data_fim: str) -> list:
    conn = criar_conector(portal_id)
    try:
        empenhos = conn.buscar_empenhos(
            termo=termo, favorecido=favorecido, cpf_cnpj=cpf_cnpj,
            unidade=unidade, data_ini=data_ini, data_fim=data_fim, ano=2026,
        )
    finally:
        conn.close()
    return empenhos


@app.get("/api/relatorio/markdown")
def api_relatorio_markdown(
    portal_id: str = Query(...),
    termo: str = Query(""),
    favorecido: str = Query(""),
    cpf_cnpj: str = Query(""),
    unidade: str = Query(""),
    data_ini: str = Query(""),
    data_fim: str = Query(""),
    titulo: str = Query(""),
):
    portal = next((p for p in listar_portais() if p.id == portal_id), None)
    if portal is None:
        raise HTTPException(404, "Portal não encontrado")
    if portal.tipo == "mt_estado":
        empenhos = _buscar_vivo(portal_id, termo, favorecido, cpf_cnpj,
                                unidade, data_ini, data_fim)
    else:
        empenhos = db.buscar(portal_id, termo=termo, favorecido=favorecido,
                             cpf_cnpj=cpf_cnpj, unidade=unidade,
                             data_ini=data_ini, data_fim=data_fim)
    md = relatorio.gerar_markdown(portal, empenhos, termo, data_ini, data_fim, titulo)
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")


@app.get("/api/relatorio/csv")
def api_relatorio_csv(
    portal_id: str = Query(...),
    termo: str = Query(""),
    favorecido: str = Query(""),
    cpf_cnpj: str = Query(""),
    unidade: str = Query(""),
    data_ini: str = Query(""),
    data_fim: str = Query(""),
):
    if _portal_tipo(portal_id) == "mt_estado":
        empenhos = _buscar_vivo(portal_id, termo, favorecido, cpf_cnpj,
                                unidade, data_ini, data_fim)
    else:
        empenhos = db.buscar(portal_id, termo=termo, favorecido=favorecido,
                             cpf_cnpj=cpf_cnpj, unidade=unidade,
                             data_ini=data_ini, data_fim=data_fim)
    csv_text = relatorio.gerar_csv(empenhos)
    return PlainTextResponse(csv_text, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=empenhos.csv"})


@app.get("/", response_class=HTMLResponse)
def index():
    path = _FRONT / "index.html"
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Frontend não encontrado</h1>")


app.mount("/static", StaticFiles(directory=str(_FRONT)), name="static")
