"""Rótulos em português para o JSON Schema das características (formulários dinâmicos).

O front monta os campos a partir do schema exposto pela API; os rótulos ficam aqui,
no backend, para que exista uma única fonte de verdade para nome de campo e opções.
"""

from typing import Any

FIELD_TITLES: dict[str, str] = {
    "enforcement_types": "O que fiscaliza",
    "max_speed_kmh": "Velocidade máxima (km/h)",
    "monitored_lanes": "Faixas monitoradas",
    "direction": "Sentido",
    "plate_recognition": "Leitura automática de placas (OCR)",
    "resolution": "Resolução",
    "night_vision": "Visão noturna",
    "color_mode": "Imagem",
    "ptz": "PTZ (pan/tilt/zoom remoto)",
    "field_of_view_degrees": "Campo de visão (graus)",
    "recording_retention_days": "Retenção da gravação (dias)",
    "video_analytics": "Analítico de vídeo embarcado",
    "scale_kind": "Tipo de pesagem",
    "max_capacity_tonnes": "Capacidade máxima (t)",
    "plate": "Placa",
    "autonomy_hours": "Autonomia (horas)",
    "camera_count": "Quantidade de câmeras",
    "access_control_methods": "Formas de controle de acesso",
    "opening_time_seconds": "Tempo de abertura (s)",
    "vehicle_loop_detector": "Laço detector de veículo",
    "service": "Serviço",
    "permit_number": "Número do alvará",
    "passenger_capacity": "Capacidade de passageiros",
    "wheelchair_accessible": "Acessível a cadeira de rodas",
    "payment_methods": "Formas de pagamento",
    "connectivity": "Conectividade",
    "receipt_printer": "Impressora de comprovante",
    "solar_powered": "Alimentação solar",
    "ownership": "Modalidade",
    "operator_name": "Operadora",
    "battery_capacity_wh": "Capacidade da bateria (Wh)",
    "gps_tracker": "Rastreador GPS",
    "engine_cc": "Cilindrada (cc)",
    "siren": "Sirene",
    "radio": "Rádio",
    "crew_capacity": "Tripulação máxima",
    "prefix": "Prefixo",
    "onboard_camera": "Câmera embarcada",
    "armored": "Blindada",
    "phases": "Fases semafóricas",
    "pedestrian_button": "Botoeira para pedestres",
    "countdown_timer": "Cronômetro regressivo",
    "adaptive": "Tempo adaptativo",
    "battery_backup": "Nobreak",
}

ENUM_LABELS: dict[str, str] = {
    "velocidade": "Velocidade",
    "avanco_semaforo": "Avanço de semáforo",
    "retorno_proibido": "Retorno proibido",
    "conversao_proibida": "Conversão proibida",
    "parada_sobre_faixa": "Parada sobre a faixa",
    "faixa_exclusiva": "Faixa exclusiva",
    "720p": "HD (720p)",
    "1080p": "Full HD (1080p)",
    "2k": "2K",
    "4k": "4K",
    "colorida": "Colorida",
    "preto_e_branco": "Preto e branco",
    "estatica": "Estática",
    "dinamica": "Dinâmica (em movimento)",
    "tag_rfid": "Tag RFID",
    "leitura_de_placa": "Leitura de placa",
    "ticket": "Tíquete",
    "manual": "Manual",
    "taxi": "Táxi",
    "mototaxi": "Mototáxi",
    "escolar": "Escolar",
    "pix": "Pix",
    "cartao_credito": "Cartão de crédito",
    "cartao_debito": "Cartão de débito",
    "dinheiro": "Dinheiro",
    "aproximacao": "Aproximação (NFC)",
    "4g": "4G",
    "5g": "5G",
    "wifi": "Wi-Fi",
    "fibra": "Fibra óptica",
    "publico": "Público",
    "compartilhado": "Compartilhado",
}


def field_title(name: str, _info: Any) -> str:
    return FIELD_TITLES.get(name, name.replace("_", " ").capitalize())


def add_enum_labels(schema: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta ``x-enum-labels`` a cada enum do schema (consumido pelo front)."""
    for definition in schema.get("$defs", {}).values():
        if "enum" in definition:
            definition["x-enum-labels"] = {
                value: ENUM_LABELS.get(str(value), str(value)) for value in definition["enum"]
            }
    return schema
