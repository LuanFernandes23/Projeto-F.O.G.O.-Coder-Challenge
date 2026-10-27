"""Contratos de endereço e coordenadas, com validação de CEP e território brasileiro."""

import re
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.domain.shared import UF, Address, GeoPoint

# Caixa envolvente do território brasileiro (com folga): barra coordenadas trocadas
# (lat/lng invertidos) e pontos fora do país, erro comum em cadastro manual.
_BRAZIL_LAT = (-34.0, 5.5)
_BRAZIL_LNG = (-74.5, -28.5)


def _normalize_cep(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 8:
        raise ValueError("CEP deve conter 8 dígitos.")
    return digits


Cep = Annotated[str, AfterValidator(_normalize_cep), Field(examples=["17500-000"])]


class GeoPointSchema(BaseModel):
    latitude: float = Field(ge=-90, le=90, examples=[-22.2139])
    longitude: float = Field(ge=-180, le=180, examples=[-49.9458])

    @model_validator(mode="after")
    def _inside_brazil(self) -> Self:
        inside = (
            _BRAZIL_LAT[0] <= self.latitude <= _BRAZIL_LAT[1]
            and _BRAZIL_LNG[0] <= self.longitude <= _BRAZIL_LNG[1]
        )
        if not inside:
            raise ValueError(
                "Coordenadas fora do território brasileiro. Verifique se latitude e "
                "longitude não estão invertidas."
            )
        return self

    def to_domain(self) -> GeoPoint:
        return GeoPoint(latitude=self.latitude, longitude=self.longitude)

    @classmethod
    def from_domain(cls, point: GeoPoint) -> "GeoPointSchema":
        return cls.model_construct(latitude=point.latitude, longitude=point.longitude)


class AddressSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    cep: Cep
    street: str = Field(min_length=2, max_length=150, examples=["Avenida Sampaio Vidal"])
    reference: str | None = Field(
        default=None,
        max_length=150,
        description='Número ou referência livre: "181", "oposto ao 181", "KM 203", "S/N"...',
        examples=["em frente ao Mercado do Tio"],
    )
    neighborhood: str = Field(min_length=2, max_length=100, examples=["Centro"])
    city: str = Field(min_length=2, max_length=100, examples=["Marília"])
    uf: UF = Field(examples=["SP"])

    def to_domain(self) -> Address:
        return Address(
            cep=self.cep,
            street=self.street,
            reference=self.reference or None,
            neighborhood=self.neighborhood,
            city=self.city,
            uf=self.uf,
        )

    @classmethod
    def from_domain(cls, address: Address) -> "AddressSchema":
        return cls.model_construct(
            cep=address.cep,
            street=address.street,
            reference=address.reference,
            neighborhood=address.neighborhood,
            city=address.city,
            uf=address.uf,
        )


class CepLookupOutput(BaseModel):
    cep: str
    street: str | None
    neighborhood: str | None
    city: str
    uf: UF
    location: GeoPointSchema | None = Field(
        description="Coordenadas aproximadas, quando o provedor as fornece."
    )
    source: str = Field(description="Provedor que respondeu (viacep, brasilapi).")
