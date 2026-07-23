"""Nota: o tipo central do domínio."""

from dataclasses import dataclass
from pathlib import Path


def preview(texto: str, limite: int = 60) -> str:
    """Prévia curta usada em notificações e na lista de notas."""
    return texto[:limite]


@dataclass(frozen=True)
class DbNote:
    id: int
    created_at: str  # ISO-8601
    text: str
    favorite: bool
    tags: tuple
    filename: str | None

    @property
    def title(self) -> str:
        if self.filename:
            return Path(self.filename).stem
        return self.created_at.replace("T", " ")

    def matches(self, consulta: str) -> bool:
        """Filtro rápido em memória (compatível com a janela de notas)."""
        consulta = consulta.strip().lower()
        return (consulta in self.text.lower()
                or consulta in self.title.lower())

    def __str__(self) -> str:
        return self.title  # logs legíveis ("nota criada: <timestamp>")
