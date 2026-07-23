"""Tradução dos atalhos de período da UI para limites de data."""

from datetime import datetime, timedelta


def periodo_desde(periodo: str, agora: datetime | None = None) -> str | None:
    """"hoje" | "7dias" | "30dias" → limite inferior ISO usado em
    search(desde=...); outro valor → None (sem filtro de data)."""
    agora = agora or datetime.now()
    if periodo == "hoje":
        inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    elif periodo == "7dias":
        inicio = agora - timedelta(days=7)
    elif periodo == "30dias":
        inicio = agora - timedelta(days=30)
    else:
        return None
    return inicio.isoformat(timespec="seconds")
