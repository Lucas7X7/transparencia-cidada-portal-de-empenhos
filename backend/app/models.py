from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Empenho:
    """Empenho normalizado de qualquer portal de transparência."""

    portal: str
    portal_id: str
    numeroAno: str
    dataEmpenho: str
    favorecido: str
    cpfCnpj: str
    unidadeGestora: str
    unidadeOrcamentaria: str
    orgao: str
    elementoDespesa: str
    naturezaDespesa: str
    fonteRecurso: str
    empenhado: float
    liquidado: float
    pago: float
    historico: str = ""
    url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def saldo(self) -> float:
        return round(self.empenhado - self.pago, 2)


@dataclass
class PortalInfo:
    id: str
    nome: str
    uf: str
    esfera: str
    tipo: str
    url: str
    config: dict[str, Any] = field(default_factory=dict)
