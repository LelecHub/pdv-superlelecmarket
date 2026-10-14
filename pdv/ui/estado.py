from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClienteVenda:
    """Cliente identificado na venda atual e a preferência escolhida (1, 2 ou 3)."""

    id: int | None = None
    nome: str = "Consumidor não identificado"
    cpf: str | None = None
    preferencia: str | None = None
    cpf_tmp: str | None = None  # entre digitar o CPF e escolher a preferência
    id_tmp: int | None = None

    def resetar(self) -> None:
        self.id = None
        self.nome = "Consumidor não identificado"
        self.cpf = None
        self.preferencia = None
        self.cpf_tmp = None
        self.id_tmp = None

    @property
    def cpf_na_nota(self) -> str | None:
        return self.cpf if self.preferencia in ("1", "3") else None

    @property
    def id_fidelidade(self) -> int | None:
        return self.id if self.preferencia in ("1", "2") else None
