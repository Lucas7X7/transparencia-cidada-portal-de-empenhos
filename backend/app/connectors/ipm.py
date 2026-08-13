from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho

# Campos padrão do grid "Empenhos por exercício" dos portais IPM.
# Estrutura compatível com Agili.Blue.Portal (portais IPM Sistemas).
_GRID_FIELDS = [
    {"field": "IdUnidadeGestora", "displayName": "Unidade gestora",
     "nameFieldTable": "Id", "aliasTable": "UG", "type": 8, "typeParam": 1,
     "operatorDefault": 1, "required": False, "checked": True, "order": 10},
    {"field": "IdEstrutFonteRecurso", "displayName": "Fonte dos recursos",
     "nameFieldTable": "IdEstrutFonteRecurso", "aliasTable": "E",
     "type": 8, "typeParam": 1, "operatorDefault": 1, "required": False,
     "checked": True, "order": 25},
    {"field": "DataInicio", "displayName": "De",
     "nameFieldTable": "DataEmpenho", "aliasTable": "E",
     "type": 3, "typeParam": 3, "operatorDefault": 1, "required": False,
     "checked": True, "order": 50},
    {"field": "DataFim", "displayName": "Até",
     "nameFieldTable": "DataEmpenho", "aliasTable": "E",
     "type": 3, "typeParam": 3, "operatorDefault": 1, "required": False,
     "checked": True, "order": 50},
    {"field": "FiltroExercicio", "displayName": "Exercício",
     "aliasTable": "E", "type": 1, "typeParam": 1, "operatorDefault": 1,
     "required": True, "checked": True, "order": 100},
    {"field": "Favorecido", "displayName": "Favorecido",
     "aliasTable": "E", "type": 2, "typeParam": 2, "operatorDefault": 12,
     "required": False, "checked": True, "order": 120,
     "valueToReplace": ".;-;/", "placeholder": "Nome, CPF ou CNPJ"},
    {"field": "IdFundo", "displayName": "Fundo",
     "aliasTable": "DO", "type": 8, "typeParam": 1, "operatorDefault": 1,
     "required": False, "checked": True, "order": 130},
    {"field": "IdClassificacaoDespesa", "displayName": "Classificação da despesa",
     "aliasTable": "E", "type": 9, "typeParam": 1, "operatorDefault": 1,
     "required": False, "checked": True, "order": 140},
    {"field": "IdNaturezaDespesa", "displayName": "Natureza de despesa",
     "nameFieldTable": "Id", "aliasTable": "ND", "type": 8, "typeParam": 1,
     "operatorDefault": 1, "required": False, "checked": True, "order": 1000},
]


class IpmConnector(PortalConnector):
    """Conector genérico para portais IPM Sistemas (transparencia.<mun>.gov.br)."""

    def _api(self, path: str) -> str:
        base = self.portal.config.get("base", self.portal.url)
        return base.rstrip("/") + path

    def _headers(self) -> dict[str, str]:
        uc = self.portal.config.get("uc", self.portal.config.get("codigo_unicom", "rondonopolis"))
        return {
            "uc": uc,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _body(self, ano: int, data_ini: str, data_fim: str, favorecido: str = "") -> list[dict]:
        fields: list[dict[str, Any]] = []
        for f in _GRID_FIELDS:
            o: dict[str, Any] = {
                "field": f["field"], "label": f["displayName"],
                "nameFieldTable": f.get("nameFieldTable", ""),
                "aliasTable": f.get("aliasTable", ""),
                "type": f["type"], "typeParam": f["typeParam"],
                "operatorDefault": f["operatorDefault"],
                "operatorValue": f["operatorDefault"],
                "checked": f["checked"], "order": f.get("order", 0),
                "required": f.get("required", False),
            }
            if f["field"] == "DataInicio":
                o["value"] = data_ini
                o["valueFinnaly"] = data_fim
            elif f["field"] == "DataFim":
                o["value"] = data_fim
            elif f["field"] == "FiltroExercicio":
                o["value"] = str(ano)
            elif f["field"] == "Favorecido":
                o["valueToReplace"] = f.get("valueToReplace", "")
                o["value"] = favorecido
            fields.append(o)
        return fields

    def _grid_url(self, page: int, size: int) -> str:
        return self._api(
            "/api/contabilidade/despesas/empenhosporexercicio/"
            "obterdadosempenhosporexercicio/"
            "?model=Agili.Blue.Portal.Shared.Contabilidade.Dto.Despesas."
            "EmpenhosPorExercicio.EmpenhosPorExercicioGridDto"
            f"&page={page}&size={size}&withCount=true"
        )

    def _fetch_page(self, ano: int, data_ini: str, data_fim: str,
                    favorecido: str, page: int, size: int) -> dict:
        body = self._body(ano, data_ini, data_fim, favorecido)
        try:
            r = self.client.post(
                self._grid_url(page, size),
                headers=self._headers(),
                content=json.dumps(body),
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao consultar portal IPM: {e}") from e

    def buscar_empenhos(self, termo: str = "", favorecido: str = "",
                        cpf_cnpj: str = "", unidade: str = "",
                        data_ini: str = "", data_fim: str = "",
                        ano: int = 2026, page_size: int = 100) -> list[Empenho]:
        fav = favorecido or cpf_cnpj
        if not data_ini:
            data_ini = f"{ano}-01-01"
        if not data_fim:
            data_fim = f"{ano}-12-31"
        out: list[Empenho] = []
        page = 0
        while True:
            data = self._fetch_page(ano, data_ini, data_fim, fav, page, page_size)
            rows = data.get("data") or []
            for row in rows:
                if unidade and self._norm(unidade) not in self._norm(
                    f"{row.get('unidadeOrc', '')} {row.get('orgao', '')}"
                ):
                    continue
                emp = self._empenho_from_row(row)
                if termo:
                    self.detalhe_empenho(emp)
                    if not self._matches(emp.historico, emp.favorecido, termo):
                        continue
                out.append(emp)
            total = int(data.get("totalResult", 0))
            page += 1
            if page * page_size >= total or not rows:
                break
        return out

    def _empenho_from_row(self, row: dict) -> Empenho:
        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=str(row.get("numeroAno", "")),
            dataEmpenho=str(row.get("dataEmpenho", ""))[:10],
            favorecido=str(row.get("nomeFavorecido", "")),
            cpfCnpj=str(row.get("cpfcnpjFavorecido", "")),
            unidadeGestora=str(row.get("unidadeGestora", "")),
            unidadeOrcamentaria=str(row.get("unidadeOrc", "")),
            orgao=str(row.get("orgao", "")),
            elementoDespesa=str(row.get("elementoDespesa", "")),
            naturezaDespesa=str(row.get("naturezaDespesa", "")),
            fonteRecurso=str(row.get("fonteRecurso", "")),
            empenhado=self._num(row.get("empenhado")),
            liquidado=self._num(row.get("liquidado")),
            pago=self._num(row.get("pago")),
            extra={"id_empenho": row.get("id")},
        )

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        emp_id = empenho.extra.get("id_empenho")
        if emp_id is None:
            try:
                emp_id = int(empenho.numeroAno.split("/")[0])
            except (ValueError, IndexError):
                return empenho
        url = self._api(
            "/api/contabilidade/contabilidade/"
            "obterDadosAbaDadosDetalhadosDespesa"
            f"?idEmpenho={emp_id}"
        )
        try:
            r = self.client.get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            return empenho
        empenho.historico = str(data.get("historico", ""))
        empenho.unidadeOrcamentaria = str(data.get("unidadeOrcamentaria", ""))
        empenho.elementoDespesa = str(
            data.get("elementoDespesa", empenho.elementoDespesa)
        )
        return empenho

    def sync_todos(self, ano: int, data_ini: str = "", data_fim: str = "",
                   page_size: int = 100) -> Iterator[Empenho]:
        """Baixa todos os empenhos do período e preenche o histórico (pode ser lento)."""
        if not data_ini:
            data_ini = f"{ano}-01-01"
        if not data_fim:
            data_fim = f"{ano}-12-31"
        page = 0
        while True:
            data = self._fetch_page(ano, data_ini, data_fim, "", page, page_size)
            rows = data.get("data") or []
            for row in rows:
                emp = self._empenho_from_row(row)
                yield emp
            total = int(data.get("totalResult", 0))
            page += 1
            if page * page_size >= total or not rows:
                break
