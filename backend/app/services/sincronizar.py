from __future__ import annotations

from app import db
from app.connectors.base import PortalConnector
from app.models import Empenho


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
    from app.connectors import criar_conector, obter_portal

    portal = obter_portal(portal_id)
    if portal is None:
        raise KeyError(f"Portal não cadastrado: {portal_id}")
    if portal.tipo in ("mt_estado",):
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
