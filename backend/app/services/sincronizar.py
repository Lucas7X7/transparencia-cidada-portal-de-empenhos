from __future__ import annotations

import logging
import time

from app import db
from app.connectors.base import PortalConnector
from app.models import Empenho

log = logging.getLogger("sincronizar")


def sincronizar(
    portal_id: str,
    ano: int,
    data_ini: str = "",
    data_fim: str = "",
    com_historico: bool = True,
) -> dict:
    """Baixa empenhos do portal e grava no cache SQLite.

    Retorna: {'total': n, 'novos': n, 'atualizados': n}
    """
    from app.connectors import criar_conector, e_live_only, obter_portal

    portal = obter_portal(portal_id)
    if portal is None:
        raise KeyError(f"Portal não cadastrado: {portal_id}")
    if e_live_only(portal):
        raise ValueError(
            "Este portal não suporta sincronização completa: use a busca (origem ao vivo)."
        )
    conn = criar_conector(portal_id)
    try:
        total = 0
        novos = 0
        atualizados = 0
        if hasattr(conn, "sync_todos"):
            for emp in conn.sync_todos(ano, data_ini, data_fim):
                total += 1
                novo = _gravar_com_historico(conn, emp, com_historico)
                if novo == "novo":
                    novos += 1
                elif novo == "atualizado":
                    atualizados += 1
        else:
            empenhos = conn.buscar_empenhos(ano=ano, data_ini=data_ini, data_fim=data_fim)
            for emp in empenhos:
                total += 1
                novo = _gravar_com_historico(conn, emp, com_historico)
                if novo == "novo":
                    novos += 1
                elif novo == "atualizado":
                    atualizados += 1
        return {"total": total, "novos": novos, "atualizados": atualizados}
    finally:
        conn.close()


def sincronizar_portal_com_status(portal_id: str, ano: int) -> None:
    """Sincroniza um portal e registra o resultado na tabela de status.

    Usado pelo worker (background) e pela sincronização em lote do próprio app.
    Não lança exceção: erros são gravados no status.
    """
    from app.connectors import listar_portais

    portal = next((p for p in listar_portais() if p.id == portal_id), None)
    if portal is None:
        log.error("Portal não encontrado: %s", portal_id)
        return
    if e_live_only(portal):
        log.info("[%s] %s — sem sincronização em lote (consulta ao vivo)", portal_id, portal.nome)
        return
    db.registrar_sync_inicio(portal_id, portal.nome)
    t0 = time.monotonic()
    try:
        res = sincronizar(portal_id, ano, "", "", com_historico=True)
        dur = time.monotonic() - t0
        db.registrar_sync_fim(portal_id, res["total"], res["novos"], res["atualizados"])
        log.info(
            "[%s] %s — %d empenhos (%d novos, %d atualizados) em %.1fs",
            portal_id, portal.nome, res["total"], res["novos"], res["atualizados"], dur,
        )
    except Exception as e:  # noqa: BLE001 — continua com os demais portais
        dur = time.monotonic() - t0
        db.registrar_sync_erro(portal_id, str(e))
        log.error("[%s] %s — erro após %.1fs: %s", portal_id, portal.nome, dur, e)


def _gravar_com_historico(conn: PortalConnector, emp: Empenho, com_historico: bool) -> str:
    anterior = db.existe(emp.portal_id, emp.numeroAno)
    if com_historico and not emp.historico:
        try:
            conn.detalhe_empenho(emp)
        except Exception:
            pass
    status = "novo" if not anterior else "atualizado"
    db.upsert_empenhos([emp])
    return status
