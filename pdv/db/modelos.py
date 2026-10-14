"""Modelos de dados compartilhados entre online, offline e UI."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from pdv.money import D


@dataclass(frozen=True)
class Promocao:
    tipo: str
    valor: Decimal
    qtd_necessaria: int
    qtd_pagante: int
    campanha: str


@dataclass
class DadosVenda:
    """Tudo o que é preciso para gravar uma venda, online ou offline.

    O `uuid_venda` é gerado na criação e viaja junto: é o que torna o reenvio seguro
    (a mesma venda enviada duas vezes vira uma só no servidor).
    """

    itens: list[dict]
    total: Decimal
    forma: str
    recebido: Decimal
    troco: Decimal
    caixa_id: int
    cliente_id: int | None = None
    cpf_nota: str | None = None
    uuid_venda: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_json(self) -> str:
        return json.dumps(
            {
                "uuid_venda": self.uuid_venda,
                "itens": [
                    {
                        "id": i["id"],
                        "nome": i.get("nome", ""),
                        "quantidade": str(i["quantidade"]),
                        "preco_unit": str(i["preco_unit"]),
                        "subtotal": str(i["subtotal"]),
                    }
                    for i in self.itens
                ],
                "total": str(self.total),
                "forma": self.forma,
                "recebido": str(self.recebido),
                "troco": str(self.troco),
                "caixa_id": self.caixa_id,
                "cliente_id": self.cliente_id,
                "cpf_nota": self.cpf_nota,
            }
        )

    @classmethod
    def from_json(cls, texto: str, uuid_venda: str | None = None) -> DadosVenda:
        d = json.loads(texto)
        return cls(
            itens=[
                {
                    "id": i["id"],
                    "nome": i.get("nome", ""),
                    "quantidade": D(i["quantidade"]),
                    "preco_unit": D(i["preco_unit"]),
                    "subtotal": D(i["subtotal"]),
                }
                for i in d["itens"]
            ],
            total=D(d["total"]),
            forma=d["forma"],
            recebido=D(d["recebido"]),
            troco=D(d["troco"]),
            caixa_id=d["caixa_id"],
            cliente_id=d.get("cliente_id"),
            cpf_nota=d.get("cpf_nota"),
            uuid_venda=uuid_venda or d.get("uuid_venda") or str(uuid.uuid4()),
        )


@dataclass
class ResultadoVenda:
    ok: bool
    msg: str
    ref: str = ""  # texto exibido no cupom: "00123" (online) ou "OFF-00007" (offline)
    offline: bool = False
