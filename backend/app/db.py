from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

from app.connectors.base import PortalConnector
from app.models import Empenho

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cache.db"
_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_USA_POSTGRES = bool(_DATABASE_URL)


def backend_nome() -> str:
    return "postgresql" if _USA_POSTGRES else "sqlite"


# ------------------------------------------------------------------
# Conexão
# ------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    if _USA_POSTGRES:
        import psycopg2

        return psycopg2.connect(_DATABASE_URL)
    if not _DB_PATH.parent.exists():
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _executar(conn, sql: str, params: tuple | list) -> None:
    """Executa SQL sem retorno, abstraindo placeholder (? no SQLite, %s no Postgres)."""
    if _USA_POSTGRES:
        sql = sql.replace("?", "%s")
    conn.execute(sql, params)


def _filas(conn, sql: str, params: tuple | list) -> list:
    if _USA_POSTGRES:
        sql = sql.replace("?", "%s")
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description or []]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def _upsert(conn, cols: list[str], params: tuple) -> None:
    """INSERT ... ON CONFLICT (id) DO UPDATE — funciona igual no SQLite e no Postgres."""
    placeholders = ", ".join(["?"] * len(cols))
    sets = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
    sql = (
        f"INSERT INTO empenhos ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {sets}"
    )
    _executar(conn, sql, params)


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------
def init_db() -> None:
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS empenhos (
        id TEXT PRIMARY KEY,
        portal TEXT NOT NULL,
        portal_id TEXT NOT NULL,
        numero_ano TEXT NOT NULL,
        data_empenho TEXT,
        favorecido TEXT,
        cpf_cnpj TEXT,
        unidade_gestora TEXT,
        unidade_orcamentaria TEXT,
        orgao TEXT,
        elemento_despesa TEXT,
        natureza_despesa TEXT,
        fonte_recurso TEXT,
        empenhado REAL,
        liquidado REAL,
        pago REAL,
        historico TEXT,
        url TEXT
    )
    """
    with _connect() as conn:
        _executar(conn, _SCHEMA, ())
        _executar(conn, "CREATE INDEX IF NOT EXISTS idx_empenhos_portal ON empenhos (portal_id)", ())
        _executar(conn, "CREATE INDEX IF NOT EXISTS idx_empenhos_data ON empenhos (data_empenho)", ())
        _executar(conn, "CREATE INDEX IF NOT EXISTS idx_empenhos_fav ON empenhos (favorecido)", ())
        conn.commit()


# ------------------------------------------------------------------
# Mapeamento
# ------------------------------------------------------------------
def _row_to_empenho(row: dict) -> Empenho:
    def g(k: str, default=""):
        v = row.get(k, default)
        return default if v is None else v

    return Empenho(
        portal=g("portal"),
        portal_id=g("portal_id"),
        numeroAno=g("numero_ano"),
        dataEmpenho=g("data_empenho"),
        favorecido=g("favorecido"),
        cpfCnpj=g("cpf_cnpj"),
        unidadeGestora=g("unidade_gestora"),
        unidadeOrcamentaria=g("unidade_orcamentaria"),
        orgao=g("orgao"),
        elementoDespesa=g("elemento_despesa"),
        naturezaDespesa=g("natureza_despesa"),
        fonteRecurso=g("fonte_recurso"),
        empenhado=float(g("empenhado", 0.0) or 0.0),
        liquidado=float(g("liquidado", 0.0) or 0.0),
        pago=float(g("pago", 0.0) or 0.0),
        historico=g("historico"),
        url=g("url"),
    )


# ------------------------------------------------------------------
# Gravação
# ------------------------------------------------------------------
_COLS = [
    "id", "portal", "portal_id", "numero_ano", "data_empenho", "favorecido",
    "cpf_cnpj", "unidade_gestora", "unidade_orcamentaria", "orgao",
    "elemento_despesa", "natureza_despesa", "fonte_recurso",
    "empenhado", "liquidado", "pago", "historico", "url",
]


def upsert_empenhos(empenhos: Iterable[Empenho]) -> int:
    n = 0
    with _connect() as conn:
        for emp in empenhos:
            params = (
                f"{emp.portal_id}|{emp.numeroAno}",
                emp.portal, emp.portal_id, emp.numeroAno, emp.dataEmpenho,
                emp.favorecido, emp.cpfCnpj, emp.unidadeGestora,
                emp.unidadeOrcamentaria, emp.orgao, emp.elementoDespesa,
                emp.naturezaDespesa, emp.fonteRecurso,
                emp.empenhado, emp.liquidado, emp.pago, emp.historico, emp.url,
            )
            _upsert(conn, _COLS, params)
            n += 1
        conn.commit()
    return n


def atualizar_historico(portal_id: str, numero_ano: str, historico: str) -> None:
    with _connect() as conn:
        _executar(
            conn,
            "UPDATE empenhos SET historico = ? WHERE portal_id = ? AND numero_ano = ?",
            (historico, portal_id, numero_ano),
        )
        conn.commit()


# ------------------------------------------------------------------
# Leitura
# ------------------------------------------------------------------
def buscar(
    portal_id: str,
    termo: str = "",
    favorecido: str = "",
    cpf_cnpj: str = "",
    unidade: str = "",
    data_ini: str = "",
    data_fim: str = "",
    min_valor: float | None = None,
    max_valor: float | None = None,
) -> list[Empenho]:
    sql = "SELECT * FROM empenhos WHERE portal_id = ?"
    params: list = [portal_id]
    if cpf_cnpj:
        sql += " AND (cpf_cnpj = ? OR favorecido LIKE ?)"
        params += [cpf_cnpj, f"%{cpf_cnpj}%"]
    elif favorecido:
        sql += " AND favorecido LIKE ?"
        params.append(f"%{favorecido}%")
    if data_ini:
        sql += " AND data_empenho >= ?"
        params.append(data_ini)
    if data_fim:
        sql += " AND data_empenho <= ?"
        params.append(data_fim)
    if min_valor is not None:
        sql += " AND empenhado >= ?"
        params.append(min_valor)
    if max_valor is not None:
        sql += " AND empenhado <= ?"
        params.append(max_valor)
    sql += " ORDER BY data_empenho"
    with _connect() as conn:
        rows = _filas(conn, sql, tuple(params))
    empenhos = [_row_to_empenho(r) for r in rows]
    if termo:
        empenhos = [
            e for e in empenhos
            if PortalConnector._matches(e.historico, e.favorecido, termo)
        ]
    return empenhos


def contar(portal_id: str) -> int:
    with _connect() as conn:
        rows = _filas(conn, "SELECT COUNT(*) c FROM empenhos WHERE portal_id = ?", (portal_id,))
    return int(rows[0]["c"])


def existe(portal_id: str, numero_ano: str) -> bool:
    with _connect() as conn:
        rows = _filas(
            conn,
            "SELECT 1 FROM empenhos WHERE portal_id = ? AND numero_ano = ?",
            (portal_id, numero_ano),
        )
    return bool(rows)
