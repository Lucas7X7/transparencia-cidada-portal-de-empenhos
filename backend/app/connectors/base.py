from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Iterator

import httpx

from app.models import Empenho, PortalInfo

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class PortalConnectorError(Exception):
    pass


class PortalConnector(ABC):
    """Interface comum para conectores de portais de transparência."""

    portal: PortalInfo

    def __init__(self, portal: PortalInfo):
        self.portal = portal
        self.client = httpx.Client(
            headers={"User-Agent": UA},
            follow_redirects=True,
            timeout=httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=60.0),
        )

    def close(self) -> None:
        self.client.close()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    @abstractmethod
    def buscar_empenhos(
        self,
        termo: str = "",
        favorecido: str = "",
        cpf_cnpj: str = "",
        unidade: str = "",
        data_ini: str = "",
        data_fim: str = "",
        ano: int = 2026,
    ) -> list[Empenho]:
        """Busca empenhos no portal. Deve preencher historico quando possível."""

    @abstractmethod
    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        """Preenche campos adicionais (historico) de um empenho."""

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------
    @staticmethod
    def _num(valor: Any) -> float:
        if valor is None:
            return 0.0
        if isinstance(valor, (int, float)):
            return float(valor)
        s = str(valor).strip()
        if not s:
            return 0.0
        neg = s.startswith("-")
        s = s.replace(".", "").replace(",", ".")
        m = re.search(r"\d+(?:\.\d+)?", s)
        if not m:
            return 0.0
        v = float(m.group(0))
        return -v if neg else v

    @staticmethod
    def _norm(termo: str) -> str:
        import unicodedata

        s = unicodedata.normalize("NFD", termo or "").lower()
        return "".join(c for c in s if unicodedata.category(c) != "Mn")

    @staticmethod
    def _matches(historico: str, fav: str, termo: str) -> bool:
        n = PortalConnector._norm
        t = n(termo)
        if not t:
            return True
        return t in n(historico) or t in n(fav)
