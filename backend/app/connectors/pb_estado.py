from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class PbEstadoConnector(PortalConnector):
    """Conector do portal de dados abertos do Estado da Paraíba.

    API pública (Swagger em https://api.dados.pb.gov.br/swagger/):
      GET /api/v1/despesas/notas_empenho?ano=&mes=&nomeCredor=&page=&per_page=
    Filtros opcionais: tipoPoder, codigoOrgao, codigoUnidade, numeroEmpenho,
    numeroEmenda, registroCGE, nomeCredor, cpfCnpj, descricaoEmpenho.

    A API devolve uma linha por (nota, grupo financeiro); o mesmo número de
    empenho pode aparecer várias vezes num mês. Os valores são agregados por
    nota para que `numeroAno` seja único (chave da tabela empenhos).
    """

    def _api_base(self) -> str:
        base = self.portal.config.get("base", "https://api.dados.pb.gov.br/api/v1")
        return base.rstrip("/")

    def _get(self, params: dict[str, Any]) -> dict:
        try:
            r = self.client.get(
                f"{self._api_base()}/despesas/notas_empenho",
                params=params,
                headers={"Accept": "application/json"},
                timeout=60,
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao consultar portal PB: {e}") from e

    def buscar_empenhos(
        self,
        termo: str = "",
        favorecido: str = "",
        cpf_cnpj: str = "",
        unidade: str = "",
        data_ini: str = "",
        data_fim: str = "",
        ano: int = 2026,
        page_size: int = 100,
    ) -> list[Empenho]:
        ano, meses = _periodo(ano, data_ini, data_fim)
        out: list[Empenho] = []
        for mes in meses:
            params: dict[str, Any] = {"ano": ano, "mes": mes, "per_page": page_size}
            if favorecido or cpf_cnpj:
                params["nomeCredor"] = favorecido or ""
                params["cpfCnpj"] = cpf_cnpj or ""
            if unidade:
                params["codigoUnidade"] = unidade
            if termo:
                params["descricaoEmpenho"] = termo
            rows = self._baixar_mes(params)
            empenhos = self._rows_para_empenhos(rows)
            if termo or favorecido or cpf_cnpj:
                empenhos = [
                    e for e in empenhos
                    if (not termo or self._matches(e.historico, e.favorecido, termo))
                    and (not (favorecido or cpf_cnpj)
                         or self._matches(e.favorecido, e.cpfCnpj, favorecido or cpf_cnpj))
                ]
            out.extend(empenhos)
        return out

    def sync_todos(self, ano: int, data_ini: str = "", data_fim: str = "",
                   page_size: int = 100) -> Iterator[Empenho]:
        ano, meses = _periodo(ano, data_ini, data_fim)
        for mes in meses:
            params: dict[str, Any] = {"ano": ano, "mes": mes, "per_page": page_size}
            rows = self._baixar_mes(params)
            yield from self._rows_para_empenhos(rows)

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _baixar_mes(self, params: dict[str, Any], max_paginas: int = 500) -> list[dict]:
        """Baixa todas as páginas de um mês. Duplicatas entre páginas são mantidas
        (são linhas diferentes do mesmo empenho) e agregadas depois."""
        rows: list[dict] = []
        pagina = 1
        while pagina <= max_paginas:
            p = dict(params)
            p["page"] = pagina
            data = self._get(p)
            bloco = data.get("dados") or []
            rows.extend(bloco)
            pag = data.get("paginacao") or {}
            total_pag = int(pag.get("total_paginas", 0) or 0)
            pagina += 1
            if pagina > total_pag or not bloco:
                break
        return rows

    def _rows_para_empenhos(self, rows: list[dict]) -> list[Empenho]:
        grupos: dict[tuple[str, Any], list[dict]] = defaultdict(list)
        for r in rows:
            grupos[(str(r.get("numeroEmpenho", "")), r.get("ano", ""))].append(r)
        out: list[Empenho] = []
        for (numero, _ano), regs in grupos.items():
            out.append(self._empenho_das_linhas(numero, _ano, regs))
        out.sort(key=lambda e: (e.dataEmpenho, e.numeroAno))
        return out

    def _empenho_das_linhas(self, numero: str, ano: Any, regs: list[dict]) -> Empenho:
        emp = sum(self._num(r.get("valorEmpenhado", 0)) for r in regs)
        liq = sum(self._num(r.get("valorLiquidado", 0)) for r in regs)
        pag = sum(self._num(r.get("valorPago", 0)) for r in regs)
        historicos: list[str] = []
        for r in regs:
            h = str(r.get("descricaoEmpenho", "")).strip()
            if h and h not in historicos:
                historicos.append(h)
        primeiro = regs[0]
        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=f"{numero}/{ano}",
            dataEmpenho=str(primeiro.get("dataEmpenho", ""))[:10],
            favorecido=str(primeiro.get("nomeCredor", "")),
            cpfCnpj=str(primeiro.get("cpfCnpj", "")),
            unidadeGestora=str(primeiro.get("codigoUnidade", "")),
            unidadeOrcamentaria=str(primeiro.get("codigoUnidade", "")),
            orgao=str(primeiro.get("nomeOrgao", "")),
            elementoDespesa=str(primeiro.get("nomeElemento", "")),
            naturezaDespesa=str(primeiro.get("nomeNatureza", "")),
            fonteRecurso=", ".join(
                str(r.get("codigoFonteRecurso", "")) for r in regs
                if r.get("codigoFonteRecurso")
            ),
            empenhado=round(emp, 2),
            liquidado=round(liq, 2),
            pago=round(pag, 2),
            historico=" | ".join(historicos),
            extra={
                "registro_cge": primeiro.get("registroCGE"),
                "processo": primeiro.get("processo"),
                "contrato": primeiro.get("contrato"),
                "modalidade_licitacao": primeiro.get("descricaoLicitacao"),
                "tipo_nota": primeiro.get("descricaoTipo"),
            },
        )


def _periodo(ano: int, data_ini: str, data_fim: str) -> tuple[int, list[int]]:
    """A API da PB é por mês; converte o intervalo de datas em lista de meses."""
    ini_mes = 1
    fim_mes = 12
    if data_ini:
        try:
            ini_mes = int(data_ini[5:7])
        except (IndexError, ValueError):
            pass
    if data_fim:
        try:
            fim_mes = int(data_fim[5:7])
        except (IndexError, ValueError):
            pass
    return ano, list(range(ini_mes, fim_mes + 1))
