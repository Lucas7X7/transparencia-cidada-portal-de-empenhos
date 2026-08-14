#!/usr/bin/env python3
"""Worker de sincronização em background.

Baixa os empenhos de todos os portais cadastrados para o banco (cache/Postgres)
em lote, um a um, e repete a cada INTERVALO_HORAS. Rode como um Background Worker
no Render (ou em qualquer servidor) — o site continua funcionando normalmente.

Uso:
    python worker.py                    # loop infinito (padrão p/ Render)
    python worker.py --uma-vez          # sincroniza todos e encerra
    python worker.py --intervalo 6      # intervalo customizado em horas
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # garante import de app.*

from app import db  # noqa: E402
from app.connectors import listar_portais  # noqa: E402
from app.services import sincronizar as sync_service  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def rodar(uma_vez: bool, intervalo_horas: float, ano: int) -> None:
    while True:
        db.resetar_sincronizacoes_ativas()
        portais = [p for p in listar_portais() if p.tipo != "mt_estado"]
        log.info("=== Iniciando rodada de sincronização: %d portais (%s) ===", len(portais), _agora())
        for portal in portais:
            try:
                sync_service.sincronizar_portal_com_status(portal.id, ano)
            except Exception as e:  # noqa: BLE001
                log.error("[%s] falha inesperada: %s", portal.id, e)
        log.info("=== Rodada concluída (%s) ===", _agora())
        if uma_vez:
            break
        log.info("Aguardando %.1f h até a próxima rodada...", intervalo_horas)
        time.sleep(intervalo_horas * 3600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Worker de sincronização de portais")
    parser.add_argument("--uma-vez", action="store_true", help="sincroniza tudo e encerra")
    parser.add_argument("--intervalo", type=float, default=24.0, help="intervalo em horas (padrão 24)")
    parser.add_argument("--ano", type=int, default=2026, help="exercício a sincronizar")
    args = parser.parse_args()

    db.init_db()
    log.info("Banco: %s", db.backend_nome())
    rodar(args.uma_vez, args.intervalo, args.ano)
