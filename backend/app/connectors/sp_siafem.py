from __future__ import annotations

import re
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class SpSiafemConnector(PortalConnector):
    """Conector do portal de transparência do Estado de São Paulo.

    API real (portal ASP.NET):
      POST https://www.transparencia.sp.gov.br/Despesas/Buscar
      body JSON: {tipoRetorno, anoExercicio, dataInicio, dataTermino, codigoFiltro,
                  nomeFavorecido, cpfCnpjFavorecido, codOrgao, codFuncao, codSubfuncao,
                  codPrograma, codAcao, codElemento, page, pageSize, totalItens}
      resposta: {items, page, pageSize, totalItems, hasNext, ultimaAtualizacao,
                 etapaAtual, totalPages, filtro}

    Etapas do drill-down:
      orgao      -> agregação por órgão   (tipoRetorno='orgao')
      favorecido -> agregação por credor  (tipoRetorno='favorecido')
      empenho    -> itens de empenho      (tipoRetorno='favorecido' + cpfCnpjFavorecido)

    O exercício de SP tem ~98 mil credores e ~650 mil empenhos, e a API só
    detalha empenhos a partir do CNPJ do credor (não aceita faixa de data sem
    credor). Uma sincronização em lote exigiria ~100 mil consultas por ano —
    inviável no ciclo de background. Por isso o portal é consultado ao vivo.
    """

    _PAGE_SIZE = 1000
    _MAX_FAVORECIDOS = 100

    def _api_base(self) -> str:
        base = (self.portal.config.get("base") or "https://www.transparencia.sp.gov.br").rstrip("/")
        if base.endswith("/api"):
            base = base[:-4]
        return base

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
            "Referer": f"{self._api_base()}/Despesas",
        }

    def _post(self, payload: dict[str, Any], timeout: int = 120) -> dict:
        try:
            r = self.client.post(
                f"{self._api_base()}/Despesas/Buscar",
                json=payload,
                headers=self._headers(),
                timeout=timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao consultar portal SP: {e}") from e
        return r.json()

    # ------------------------------------------------------------------
    # Busca ao vivo
    # ------------------------------------------------------------------
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
        """Busca ao vivo no portal de SP.

        - Com CPF/CNPJ: vai direto à etapa de empenho do credor.
        - Com nome: primeiro localiza os credores que casam (etapa favorecido,
          ordenados por valor empenhado), depois busca os empenhos de cada um.
        - Faixa de data só é aplicada na etapa de empenho (o servidor SP não
          aceita data sem credor).
        """
        nome = (favorecido or termo or "").strip()
        cpf = self._norm_cpf(cpf_cnpj)
        cod_orgao = self._cod_orgao(unidade)

        empenhos: list[Empenho] = []
        if cpf:
            empenhos = self._paginar_empenhos(
                cpf=cpf, cod_orgao=cod_orgao, data_ini=data_ini,
                data_fim=data_fim, ano=ano,
            )
        elif nome:
            credores = self._buscar_credores(nome, cod_orgao=cod_orgao, ano=ano)
            credores.sort(key=lambda c: c.get("vl_empenhado") or 0, reverse=True)
            for credor in credores[: self._MAX_FAVORECIDOS]:
                cnpj_credor = credor.get("cnpj_cpf_favorecido")
                if not cnpj_credor:
                    continue
                empenhos.extend(self._paginar_empenhos(
                    cpf=cnpj_credor, cod_orgao=cod_orgao, data_ini=data_ini,
                    data_fim=data_fim, ano=ano,
                ))

        if termo:
            t = self._norm(termo)
            empenhos = [e for e in empenhos if t in self._norm(e.favorecido)]
        return empenhos

    def _buscar_credores(self, nome: str, cod_orgao: str | None, ano: int) -> list[dict]:
        payload = self._payload_base(ano)
        payload["tipoRetorno"] = "favorecido"
        payload["nomeFavorecido"] = nome
        if cod_orgao:
            payload["codOrgao"] = cod_orgao
        return self._paginar_itens(payload)

    def _paginar_empenhos(self, cpf: str, cod_orgao: str | None,
                          data_ini: str, data_fim: str, ano: int) -> list[Empenho]:
        payload = self._payload_base(ano)
        payload["tipoRetorno"] = "favorecido"
        payload["cpfCnpjFavorecido"] = cpf
        if cod_orgao:
            payload["codOrgao"] = cod_orgao
        if data_ini:
            payload["dataInicio"] = data_ini
        if data_fim:
            payload["dataTermino"] = data_fim
        itens = self._paginar_itens(payload)
        return [self._normalizar_empenho(it) for it in itens]

    def _paginar_itens(self, payload: dict[str, Any]) -> list[dict]:
        itens: list[dict] = []
        page = 1
        while True:
            payload["page"] = page
            dados = self._post(payload)
            pagina_itens = dados.get("items") or []
            itens.extend(pagina_itens)
            total_pages = dados.get("totalPages") or 0
            if page >= total_pages or not pagina_itens:
                break
            page += 1
        return itens

    def _payload_base(self, ano: int) -> dict[str, Any]:
        return {
            "tipoRetorno": "favorecido",
            "anoExercicio": int(ano or 2026),
            "dataInicio": None,
            "dataTermino": None,
            "codigoFiltro": None,
            "nomeFavorecido": None,
            "cpfCnpjFavorecido": None,
            "codOrgao": None,
            "codFuncao": None,
            "codSubfuncao": None,
            "codPrograma": None,
            "codAcao": None,
            "codElemento": None,
            "page": 1,
            "pageSize": self._PAGE_SIZE,
            "totalItens": 0,
        }

    @staticmethod
    def _norm_cpf(s: str) -> str:
        return re.sub(r"[\s.\-/\u2013\u2014]", "", s or "").strip()

    @staticmethod
    def _cod_orgao(unidade: str) -> str | None:
        if not unidade:
            return None
        m = re.match(r"^(\d+)$", str(unidade).strip())
        return m.group(1) if m else None

    def _normalizar_empenho(self, item: dict[str, Any]) -> Empenho:
        def s(campo: str) -> str:
            valor = item.get(campo)
            return "" if valor is None else str(valor)

        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=s("num_empenho"),
            dataEmpenho=s("data_registro_empenho")[:10],
            favorecido=s("nome_favorecido"),
            cpfCnpj=s("cnpj_cpf_favorecido"),
            unidadeGestora=s("nome_ug"),
            unidadeOrcamentaria=s("nome_uo"),
            orgao=s("nome_orgao"),
            elementoDespesa=s("nome_elemento"),
            naturezaDespesa=s("nome_categoria_despesa"),
            fonteRecurso=s("nome_fonte"),
            empenhado=self._num(item.get("vl_empenhado", 0)),
            liquidado=self._num(item.get("vl_liquidado", 0)),
            pago=self._num(item.get("vl_pago", 0)),
            historico="",
            url=f"{self._api_base()}/Despesas",
            extra={
                "num_processo": s("num_processo"),
                "cod_orgao": s("cod_orgao"),
                "cod_uo": s("cod_uo"),
                "cod_ug": s("cod_ug"),
                "cod_fonte": s("cod_fonte"),
                "cod_elemento": s("cod_elemento"),
                "indicador_restos": s("indicador_restos"),
                "nome_funcao": s("nome_funcao"),
                "nome_programa": s("nome_programa"),
                "nome_acao": s("nome_acao"),
                "nome_tipo_licitacao": s("nome_tipo_licitacao"),
                "vl_pago_rp": self._num(item.get("vl_pago_rp", 0)),
            },
        )

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho

    def sync_todos(self, ano: int = 2026, data_ini: str = "",
                   data_fim: str = "", **_) -> Iterator[Empenho]:
        raise PortalConnectorError(
            "Portal SP não possui sincronização em lote; a busca é feita ao vivo."
        )
