"""Objetos de valor compartilhados entre os agregados do domínio."""

from dataclasses import dataclass
from enum import StrEnum


class UF(StrEnum):
    AC = "AC"
    AL = "AL"
    AP = "AP"
    AM = "AM"
    BA = "BA"
    CE = "CE"
    DF = "DF"
    ES = "ES"
    GO = "GO"
    MA = "MA"
    MT = "MT"
    MS = "MS"
    MG = "MG"
    PA = "PA"
    PB = "PB"
    PR = "PR"
    PE = "PE"
    PI = "PI"
    RJ = "RJ"
    RN = "RN"
    RS = "RS"
    RO = "RO"
    RR = "RR"
    SC = "SC"
    SP = "SP"
    SE = "SE"
    TO = "TO"


@dataclass(frozen=True, slots=True)
class GeoPoint:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class Address:
    """Endereço de instalação do equipamento ou da base.

    ``reference`` é texto livre ("número 181", "oposto ao número 181", "KM 203", "S/N",
    "em frente ao Mercado do Tio"), porque nas vias nem tudo tem número.
    """

    cep: str
    street: str
    reference: str | None
    neighborhood: str
    city: str
    uf: UF


@dataclass(frozen=True, slots=True)
class PageRequest:
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    total: int
    limit: int
    offset: int
