from __future__ import annotations

import re
from urllib.parse import urlencode, quote
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class SpSiafemConnector(PortalConnector):
    """Conector do portal de transparência de São Paulo (Siafem).
    
    API: https://www.transparencia.sp.gov.br/api/
    
    Este conector integra com a API do Siafem (Sistema Integrado de Administração
    Financeira do Estado de São Paulo), acessando dados de empenhos, liquidações e pagamentos.
    
    Fluxo:
      1. POST /despesa/empenho → busca empenhos por filtros
      2. GET /despesa/empenho/{id} → detalhe completo do empenho
    """

    def _api_base(self) -> str:
        """Retorna URL base da API, configurável."""
        base = self.portal.config.get("base", "https://www.transparencia.sp.gov.br/api")
        return base.rstrip("/")

    def _get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> str:
        """Faz requisição GET com tratamento de erro."""
        try:
            r = self.client.get(
                url,
                params=params,
                headers={"Accept": "application/json", "Referer": self.portal.url},
                timeout=timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao consultar portal SP: {e}") from e
        return r.text

    def _post(self, url: str, data: dict[str, Any] | None = None, timeout: int = 30) -> dict:
        """Faz requisição POST com tratamento de erro."""
        try:
            r = self.client.post(
                url,
                json=data,
                headers={"Accept": "application/json", "Referer": self.portal.url},
                timeout=timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao consultar portal SP: {e}") from e
        return r.json()

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
        """Busca empenhos no portal de SP com múltiplos filtros.
        
        Args:
            termo: Busca por palavra-chave (história do empenho)
            favorecido: Nome do favorecido/credor
            cpf_cnpj: CPF ou CNPJ do favorecido
            unidade: Unidade gestora
            data_ini: Data inicial (YYYY-MM-DD)
            data_fim: Data final (YYYY-MM-DD)
            ano: Exercício fiscal
            
        Returns:
            Lista de empenhos normalizados
        """
        
        # Construir filtros para a API
        filters = {
            "ano": ano,
            "pagina": 1,
            "registros_por_pagina": 100,
        }
        
        if favorecido:
            filters["favorecido"] = favorecido
        if cpf_cnpj:
            filters["cnpj"] = re.sub(r"[^0-9]", "", cpf_cnpj)
        if unidade:
            filters["unidade"] = unidade
        if data_ini:
            filters["data_inicial"] = data_ini
        if data_fim:
            filters["data_final"] = data_fim
        
        empenhos: list[Empenho] = []
        pagina = 1
        
        try:
            while True:
                filters["pagina"] = pagina
                
                # Chamar API de busca
                resultado = self._post(
                    f"{self._api_base()}/despesa/empenho/buscar",
                    data=filters,
                    timeout=60,
                )
                
                if not resultado.get("sucesso"):
                    break
                
                dados = resultado.get("dados", [])
                if not dados:
                    break
                
                for item in dados:
                    empenho = self._normalizar_empenho(item)
                    
                    # Filtro por termo (busca em histórico e favorecido)
                    if termo and not self._matches(
                        empenho.historico,
                        empenho.favorecido,
                        termo
                    ):
                        continue
                    
                    empenhos.append(empenho)
                
                # Verificar se há mais páginas
                total = resultado.get("total", 0)
                registros_retornados = len(dados)
                if registros_retornados < filters["registros_por_pagina"]:
                    break
                
                pagina += 1
                
        except PortalConnectorError as e:
            print(f"Aviso: {e}")
        
        return empenhos

    def _normalizar_empenho(self, item: dict[str, Any]) -> Empenho:
        """Converte resposta da API em modelo Empenho normalizado."""
        
        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=f"{item.get('numero', '')}/{item.get('ano', '')}",
            dataEmpenho=item.get("data_empenho", ""),
            favorecido=item.get("nome_favorecido", ""),
            cpfCnpj=item.get("cnpj_favorecido", ""),
            unidadeGestora=item.get("unidade_gestora", ""),
            unidadeOrcamentaria=item.get("unidade_orcamentaria", ""),
            orgao=item.get("orgao", ""),
            elementoDespesa=item.get("elemento_despesa", ""),
            naturezaDespesa=item.get("natureza_despesa", ""),
            fonteRecurso=item.get("fonte_recurso", ""),
            empenhado=self._num(item.get("valor_empenhado", 0)),
            liquidado=self._num(item.get("valor_liquidado", 0)),
            pago=self._num(item.get("valor_pago", 0)),
            historico=item.get("historico", ""),
            url=f"{self.portal.url}/empenho/{item.get('id', '')}",
            extra={
                "id_sp": item.get("id"),
                "modalidade": item.get("modalidade"),
                "dotacao": item.get("dotacao"),
                "banco": item.get("banco"),
                "conta": item.get("numero_conta"),
                "agencia": item.get("agencia"),
            },
        )

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        """Busca detalhes completos de um empenho (histórico completo e movimentações).
        
        Args:
            empenho: Empenho base com id_sp preenchido
            
        Returns:
            Empenho com histórico e detalhes completos
        """
        
        if not empenho.extra or not empenho.extra.get("id_sp"):
            return empenho
        
        try:
            detalhe = self._post(
                f"{self._api_base()}/despesa/empenho/{empenho.extra['id_sp']}",
                timeout=30,
            )
            
            if not detalhe.get("sucesso"):
                return empenho
            
            dados = detalhe.get("dados", {})
            
            # Atualizar campos com detalhes
            empenho.historico = dados.get("historico_completo", empenho.historico)
            empenho.liquidado = self._num(dados.get("valor_liquidado", empenho.liquidado))
            empenho.pago = self._num(dados.get("valor_pago", empenho.pago))
            
            # Adicionar movimentações ao extra
            empenho.extra["movimentacoes"] = dados.get("movimentacoes", [])
            
        except PortalConnectorError:
            pass
        
        return empenho
