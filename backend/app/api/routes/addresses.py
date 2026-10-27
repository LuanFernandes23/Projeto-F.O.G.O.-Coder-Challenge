"""Autopreenchimento de endereço por CEP."""

from fastapi import APIRouter

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.services import AddressServiceDep
from app.api.routes.common import problems
from app.schemas.location import CepLookupOutput, GeoPointSchema

router = APIRouter(prefix="/addresses", tags=["Endereços"])


@router.get(
    "/cep/{cep}",
    response_model=CepLookupOutput,
    summary="Consultar CEP (ViaCEP com fallback para BrasilAPI)",
    responses=problems(401, 404, 422, 503),
)
async def lookup_cep(cep: str, service: AddressServiceDep, _user: CurrentUser) -> CepLookupOutput:
    address = await service.lookup(cep)
    return CepLookupOutput(
        cep=address.cep,
        street=address.street,
        neighborhood=address.neighborhood,
        city=address.city,
        uf=address.uf,
        location=GeoPointSchema.from_domain(address.location) if address.location else None,
        source=address.source,
    )
