"""Dados de referência: tipos de equipamento previstos no enunciado.

Os códigos de ``attributes_schema_key`` precisam existir em
``app.schemas.equipment_attributes.ATTRIBUTE_SCHEMAS`` (há teste garantindo isso).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23 00:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = sa.table(
    "equipment_types",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("category", sa.String),
    sa.column("icon", sa.String),
    sa.column("is_mobile", sa.Boolean),
    sa.column("is_vehicle", sa.Boolean),
    sa.column("attributes_schema_key", sa.String),
    sa.column("description", sa.String),
)

# (code, nome, categoria, ícone, móvel?, viatura?, descrição)
_ROWS = [
    ("radar", "Radar de fiscalização", "fiscalizacao", "radar", False, False,
     "Velocidade, avanço de semáforo, retorno/conversão proibida, faixa exclusiva."),
    ("camera", "Câmera de videomonitoramento", "monitoramento", "cctv", False, False,
     "Câmeras fixas ou PTZ, com ou sem visão noturna."),
    ("balanca", "Balança de caminhão", "fiscalizacao", "scale", False, False,
     "Pesagem estática ou dinâmica (WIM) de veículos de carga."),
    ("veiculo_fiscalizacao_autonomo", "Veículo autônomo de fiscalização do rotativo",
     "fiscalizacao", "robot-car", True, False,
     "Veículo autônomo que fiscaliza o estacionamento rotativo por leitura de placas."),
    ("cancela", "Cancela automatizada", "controle_acesso", "barrier", False, False,
     "Controle de acesso de veículos a áreas restritas ou estacionamentos."),
    ("veiculo_transporte", "Veículo de transporte (táxi, mototáxi, escolar)", "transporte",
     "taxi", True, False, "Veículos de transporte público individual ou escolar."),
    ("totem_estacionamento", "Totem de autoatendimento do rotativo", "atendimento", "kiosk",
     False, False, "Pagamento e emissão de tíquete do estacionamento rotativo."),
    ("patinete", "Patinete elétrico", "micromobilidade", "scooter", True, False,
     "Patinetes públicos ou compartilhados."),
    ("moto_agente", "Moto de agente de trânsito", "frota_operacional", "motorcycle", True, True,
     "Motocicleta operacional atribuída a agentes."),
    ("viatura", "Viatura (Guarda Municipal / Polícia Militar)", "frota_operacional",
     "patrol-car", True, True, "Viatura operacional atribuída a equipes."),
    ("semaforo", "Controlador semafórico", "controle_trafego", "traffic-light", False, False,
     "Controlador de cruzamento semaforizado."),
    ("outro", "Outro equipamento", "outro", "device", False, False,
     "Equipamentos sem schema próprio: características livres."),
]


def upgrade() -> None:
    op.bulk_insert(
        _TYPES,
        [
            {
                "code": code,
                "name": name,
                "category": category,
                "icon": icon,
                "is_mobile": is_mobile,
                "is_vehicle": is_vehicle,
                "attributes_schema_key": code,
                "description": description,
            }
            for code, name, category, icon, is_mobile, is_vehicle, description in _ROWS
        ],
    )


def downgrade() -> None:
    codes = ", ".join(f"'{row[0]}'" for row in _ROWS)
    op.execute(f"DELETE FROM equipment_types WHERE code IN ({codes})")  # noqa: S608
