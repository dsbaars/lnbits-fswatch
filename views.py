from fastapi import APIRouter, Depends

from lnbits.core.views.generic import index
from lnbits.decorators import check_account_exists

fswatch_generic_router = APIRouter()

fswatch_generic_router.add_api_route(
    "/", methods=["GET"], endpoint=index, dependencies=[Depends(check_account_exists)]
)
