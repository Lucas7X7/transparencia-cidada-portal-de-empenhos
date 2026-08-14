from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.connectors.base import PortalConnector
from app.connectors.ipm import IpmConnector
from app.connectors.mt_estado import MtEstadoConnector
from app.connectors.sp_siafem import SpSiafemConnector
from app.models import PortalInfo

_CONFIG_FILE = Path(__file__).resolve().parent / "config" / "portals.json"

_CONNECTOR_TYPES: dict[str, type[PortalConnector]] = {
    "ipm": IpmConnector,
    "mt_estado": MtEstadoConnector,
    "sp_siafem": SpSiafemConnector,
}


def _default_config() -> list[dict[str, Any]]:
    return [
        {
            "id": "rondonopolis",
            "nome": "Prefeitura de Rondonópolis",
            "uf": "MT",
            "esfera": "municipal",
            "tipo": "ipm",
            "url": "https://transparencia.rondonopolis.mt.gov.br",
            "config": {"uc": "rondonopolis"},
        },
        {
            "id": "mt-estado",
            "nome": "Governo do Estado de Mato Grosso",
            "uf": "MT",
            "esfera": "estadual",
            "tipo": "mt_estado",
            "url": "https://www.transparencia.mt.gov.br",
            "config": {
                "base": "https://consultas.transparencia.mt.gov.br/despesa/por_favorecido/"
            },
        },
        {
            "id": "sp-estado",
            "nome": "Governo do Estado de São Paulo",
            "uf": "SP",
            "esfera": "estadual",
            "tipo": "sp_siafem",
            "url": "https://www.transparencia.sp.gov.br",
            "config": {
                "base": "https://www.transparencia.sp.gov.br/api"
            },
        },
    ]


def _load() -> list[PortalInfo]:
    if _CONFIG_FILE.exists():
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    else:
        raw = _default_config()
    return [PortalInfo(**entry) for entry in raw]


def listar_portais() -> list[PortalInfo]:
    return _load()


def obter_portal(portal_id: str) -> PortalInfo | None:
    for p in _load():
        if p.id == portal_id:
            return p
    return None


def criar_conector(portal_id: str) -> PortalConnector:
    portal = obter_portal(portal_id)
    if portal is None:
        raise KeyError(f"Portal não cadastrado: {portal_id}")
    cls = _CONNECTOR_TYPES.get(portal.tipo)
    if cls is None:
        raise KeyError(f"Tipo de conector não suportado: {portal.tipo}")
    return cls(portal)
