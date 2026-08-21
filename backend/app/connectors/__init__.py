from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.connectors.base import PortalConnector
from app.connectors.ipm import IpmConnector
from app.connectors.mt_estado import MtEstadoConnector
from app.connectors.pb_estado import PbEstadoConnector
from app.connectors.sp_siafem import SpSiafemConnector
from app.connectors.go_estado import GoEstadoConnector
from app.connectors.pe_estado import PeEstadoConnector
from app.connectors.mg_estado import MgEstadoConnector
from app.connectors.ms_estado import MsEstadoConnector
from app.connectors.ac_estado import AcEstadoConnector
from app.connectors.pa_estado import PaEstadoConnector
from app.connectors.ro_estado import RoEstadoConnector
from app.connectors.sc_estado import ScEstadoConnector
from app.connectors.rn_estado import RnEstadoConnector
from app.connectors.es_estado import EsEstadoConnector
from app.connectors.df_estado import DfEstadoConnector
from app.connectors.rr_estado import RrEstadoConnector
from app.connectors.ap_estado import ApEstadoConnector
from app.models import PortalInfo

_CONFIG_FILE = Path(__file__).resolve().parent / "config" / "portals.json"

_CONNECTOR_TYPES: dict[str, type[PortalConnector]] = {
    "ipm": IpmConnector,
    "mt_estado": MtEstadoConnector,
    "pb_estado": PbEstadoConnector,
    "sp_siafem": SpSiafemConnector,
    "go_estado": GoEstadoConnector,
    "pe_estado": PeEstadoConnector,
    "mg_estado": MgEstadoConnector,
    "ms_estado": MsEstadoConnector,
    "ac_estado": AcEstadoConnector,
    "pa_estado": PaEstadoConnector,
    "ro_estado": RoEstadoConnector,
    "sc_estado": ScEstadoConnector,
    "rn_estado": RnEstadoConnector,
    "es_estado": EsEstadoConnector,
    "df_estado": DfEstadoConnector,
    "rr_estado": RrEstadoConnector,
    "ap_estado": ApEstadoConnector,
}

# Portais consultados ao vivo (sem sincronização em lote viável).
LIVE_ONLY_TIPOS: frozenset[str] = frozenset({
    "mt_estado", "sp_siafem", "pe_estado", "ac_estado", "pa_estado", "ro_estado",
})


def e_live_only(portal: PortalInfo) -> bool:
    """True se o portal é consultado ao vivo (sem cache em lote)."""
    return portal.tipo in LIVE_ONLY_TIPOS


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
                "base": "https://www.transparencia.sp.gov.br"
            },
        },
        {
            "id": "go-estado",
            "nome": "Governo do Estado de Goiás",
            "uf": "GO",
            "esfera": "estadual",
            "tipo": "go_estado",
            "url": "https://transparencia.go.gov.br",
            "config": {
                "base": "https://dadosabertos.go.gov.br",
                "resource_id": "3048c428-83cc-45f9-af01-4d0ecb44d078",
            },
        },
        {
            "id": "pe-estado",
            "nome": "Governo do Estado de Pernambuco",
            "uf": "PE",
            "esfera": "estadual",
            "tipo": "pe_estado",
            "url": "https://transparencia.pe.gov.br",
            "config": {
                "base": "https://sistemas.tce.pe.gov.br/DadosAbertos",
            },
        },
        {
            "id": "mg-estado",
            "nome": "Governo do Estado de Minas Gerais",
            "uf": "MG",
            "esfera": "estadual",
            "tipo": "mg_estado",
            "url": "https://transparencia.mg.gov.br",
            "config": {
                "resources": {
                    "2022": "c8757609-bd2e-4864-a75e-f39c72d025f4",
                    "2023": "ab2a08af-7db8-407a-a4b4-a91e942eef55",
                    "2024": "38eafdd6-bc1e-4bf9-bc39-bf5842380d6c",
                    "2025": "2ef02d2b-655e-44a0-aaeb-bdac5c222871",
                    "2026": "c5edcee8-e67f-4352-b499-d578625669b4",
                }
            },
        },
        {
            "id": "ms-estado",
            "nome": "Governo do Estado de Mato Grosso do Sul",
            "uf": "MS",
            "esfera": "estadual",
            "tipo": "ms_estado",
            "url": "https://www.transparencia.ms.gov.br",
            "config": {},
        },
        {
            "id": "ac-estado",
            "nome": "Governo do Estado do Acre",
            "uf": "AC",
            "esfera": "estadual",
            "tipo": "ac_estado",
            "url": "https://transparencia.ac.gov.br",
            "config": {},
        },
        {
            "id": "pa-estado",
            "nome": "Governo do Estado do Pará",
            "uf": "PA",
            "esfera": "estadual",
            "tipo": "pa_estado",
            "url": "https://www.transparencia.pa.gov.br",
            "config": {
                "base": "https://api-notas-empenho.sistemas.pa.gov.br",
            },
        },
        {
            "id": "ro-estado",
            "nome": "Governo do Estado de Rondônia",
            "uf": "RO",
            "esfera": "estadual",
            "tipo": "ro_estado",
            "url": "https://transparencia.ro.gov.br",
            "config": {},
        },
        {
            "id": "sc-estado",
            "nome": "Governo do Estado de Santa Catarina",
            "uf": "SC",
            "esfera": "estadual",
            "tipo": "sc_estado",
            "url": "https://transparencia.sc.gov.br",
            "config": {
                "base": "https://api-portal-transparencia.apps.sm.okd4.ciasc.sc.gov.br",
            },
        },
        {
            "id": "rn-estado",
            "nome": "Governo do Estado do Rio Grande do Norte",
            "uf": "RN",
            "esfera": "estadual",
            "tipo": "rn_estado",
            "url": "https://transparencia.rn.gov.br",
            "config": {},
        },
        {
            "id": "es-estado",
            "nome": "Governo do Estado do Espírito Santo",
            "uf": "ES",
            "esfera": "estadual",
            "tipo": "es_estado",
            "url": "https://transparencia.es.gov.br",
            "config": {
                "dataset_id": "99e16b13-0e6f-4504-8544-00de842ab1fd",
            },
        },
        {
            "id": "df-estado",
            "nome": "Governo do Distrito Federal",
            "uf": "DF",
            "esfera": "estadual",
            "tipo": "df_estado",
            "url": "https://www.transparencia.df.gov.br",
            "config": {
                "base": "https://www.dados.df.gov.br",
                "slug": "portal-da-transparencia-despesas-da-administracao-publica-do-distrito-federal",
            },
        },
        {
            "id": "rr-estado",
            "nome": "Governo do Estado de Roraima",
            "uf": "RR",
            "esfera": "estadual",
            "tipo": "rr_estado",
            "url": "https://transparencia.rr.gov.br",
            "config": {},
        },
        {
            "id": "ap-estado",
            "nome": "Governo do Estado do Amapá",
            "uf": "AP",
            "esfera": "estadual",
            "tipo": "ap_estado",
            "url": "https://transparencia.ap.gov.br",
            "config": {},
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
