#!/usr/bin/env python3
"""Gera backend/app/config/portals.json a partir da lista de portais da AgiliCloud.

A AgiliCloud (nova geração IPM Sistemas) expõe a mesma API que os portais IPM
clássicos; a diferença é a URL base (https://transparencia.agilicloud.com.br/api/)
e o cabeçalho `uc` (shortname do cliente). Este script consulta `seletor/get`,
valida se cada cliente tem dados de empenhos e gera a configuração dos portais.

Uso:
    .venv/Scripts/python scripts/gerar_portais.py            # gera e salva portals.json
    .venv/Scripts/python scripts/gerar_portais.py --dry-run  # só imprime no terminal
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

API_BASE = "https://transparencia.agilicloud.com.br/api/"
API_HOST = "https://transparencia.agilicloud.com.br"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PortalTransparencia"
CONFIG_FILE = (Path(__file__).resolve().parent.parent / "backend" / "app" / "connectors" / "config" / "portals.json")

# Campos do grid "Empenhos por exercício" (mesma estrutura dos portais IPM clássicos).
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


def _grid_body(ano: int) -> list[dict[str, Any]]:
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
            o["value"] = f"{ano}-01-01"
            o["valueFinnaly"] = f"{ano}-12-31"
        elif f["field"] == "DataFim":
            o["value"] = f"{ano}-12-31"
        elif f["field"] == "FiltroExercicio":
            o["value"] = str(ano)
        elif f["field"] == "Favorecido":
            o["valueToReplace"] = f.get("valueToReplace", "")
            o["value"] = ""
        fields.append(o)
    return fields


def _count_empenhos(client: httpx.Client, uc: str, ano: int) -> int | None:
    """Retorna o total de empenhos do cliente num ano, ou None se o portal falhar."""
    url = API_BASE + (
        "contabilidade/despesas/empenhosporexercicio/obterdadosempenhosporexercicio/"
        "?model=Agili.Blue.Portal.Shared.Contabilidade.Dto.Despesas."
        "EmpenhosPorExercicio.EmpenhosPorExercicioGridDto"
        "&page=0&size=1&withCount=true"
    )
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Content-Type": "application/json; charset=utf-8", "uc": uc}
    try:
        r = client.post(url, headers=headers, content=json.dumps(_grid_body(ano)),
                        timeout=httpx.Timeout(connect=8, read=30, write=8, pool=8))
        if r.status_code == 200:
            return int(r.json().get("totalResult", 0) or 0)
    except httpx.HTTPError:
        pass
    return None


def _classificar(nome: str, short: str) -> str:
    """Classifica a esfera: municipal, estadual, legislativa, consórcio, previdência, autarquia."""
    n = nome.upper()
    if short.startswith("cam"):
        return "legislativo"
    if n.startswith("CONS"):
        return "consorcio"
    if n.startswith("PREV") or n.startswith("FUNDO MUNICIPAL DE PREVID"):
        return "previdencia"
    if n.startswith("PREF.") or n.startswith("PREFEITURA") or n.startswith("MUNICIPIO DE") or n.startswith("MUNICIPIO -"):
        return "municipal"
    if "GOVERNO" in n or n.startswith("ESTADO"):
        return "estadual"
    return "autarquia"


def _esfera_label(esfera: str) -> str:
    labels = {
        "municipal": "municipal",
        "estadual": "estadual",
        "legislativo": "municipal (câmara)",
        "consorcio": "intermunicipal",
        "previdencia": "municipal (previdência)",
        "autarquia": "municipal (autarquia)",
    }
    return labels.get(esfera, esfera)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="não salva o arquivo, apenas imprime no terminal")
    parser.add_argument("--ano-inicial", type=int, default=2024,
                        help="primeiro ano a validar (default: 2024)")
    parser.add_argument("--ano-final", type=int, default=2026,
                        help="último ano a validar (default: 2026)")
    args = parser.parse_args()

    client = httpx.Client()
    try:
        r = client.get(API_BASE + "seletor/get",
                       headers={"User-Agent": UA, "Accept": "application/json",
                                "uc": "prefguarantanorte-mt"}, timeout=30)
        r.raise_for_status()
        clientes = r.json()
    except httpx.HTTPError as e:
        print(f"Erro ao consultar a lista de portais: {e}", file=sys.stderr)
        return 1

    portais: list[dict[str, Any]] = []
    sem_dados: list[str] = []
    anos = list(range(args.ano_final, args.ano_inicial - 1, -1))

    # Portais já cadastrados que não são da AgiliCloud (ex.: IPM clássico, MT estadual)
    # são preservados. O ID dos clientes AgiliCloud é o `shortname`.
    extras: dict[str, dict[str, Any]] = {
        "rondonopolis": {
            "id": "rondonopolis",
            "nome": "Prefeitura de Rondonópolis",
            "uf": "MT",
            "esfera": "municipal",
            "tipo": "ipm",
            "url": "https://transparencia.rondonopolis.mt.gov.br",
            "config": {"uc": "rondonopolis"},
        },
        "mt-estado": {
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
    }
    if CONFIG_FILE.exists():
        try:
            for p in json.loads(CONFIG_FILE.read_text(encoding="utf-8")):
                base = str(p.get("config", {}).get("base", ""))
                if "agilicloud.com.br" in base:
                    continue  # gerado automaticamente abaixo
                extras[p["id"]] = p
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    for c in clientes:
        short = c.get("shortname", "")
        if not short:
            continue
        nome = c.get("nomeRazaoSocial", short).strip()
        uf = c.get("uf", "").strip()
        if uf == "MT":
            prefixo = "https://transparencia.agilicloud.com.br/"
        else:
            prefixo = "https://transparencia.agilicloud.com.br/"
        total = None
        for ano in anos:
            total = _count_empenhos(client, short, ano)
            if total:
                break
        if total is None:
            print(f"  [erro] {short:35} não respondeu")
            continue
        if total == 0:
            sem_dados.append(short)
            print(f"  [sem dados] {short:35} nenhum empenho em {anos}")
            continue
        esfera = _classificar(nome, short)
        portais.append({
            "id": short,
            "nome": nome,
            "uf": uf,
            "esfera": _esfera_label(esfera),
            "tipo": "ipm",
            "url": prefixo.rstrip("/"),
            "config": {"base": API_HOST, "uc": short},
        })
        print(f"  [ok] {short:35} {nome[:38]:38} {uf} ({total} empenhos)")

    portais.sort(key=lambda p: (p["uf"], p["nome"]))
    portais.extend(sorted(extras.values(), key=lambda p: (p["uf"], p["nome"])))

    if sem_dados:
        print(f"\nClientes sem dados de empenhos: {len(sem_dados)}")
        for s in sem_dados:
            print(f"  - {s}")

    print(f"\nTotal de portais com dados: {len(portais)}")

    if args.dry_run:
        print(json.dumps(portais, ensure_ascii=False, indent=2))
        return 0

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(portais, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"\nConfiguração salva em: {CONFIG_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
