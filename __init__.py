import asyncio

from fastapi import APIRouter
from loguru import logger

from lnbits.tasks import create_permanent_unique_task

from .crud import db
from .tasks import watch_funding_source
from .views import fswatch_generic_router
from .views_api import fswatch_api_router

fswatch_ext: APIRouter = APIRouter(prefix="/fswatch", tags=["Funding Source Watch"])
fswatch_ext.include_router(fswatch_generic_router)
fswatch_ext.include_router(fswatch_api_router)

fswatch_static_files = [
    {
        "path": "/fswatch/static",
        "name": "fswatch_static",
    }
]

scheduled_tasks: list[asyncio.Task] = []


def fswatch_stop():
    for task in scheduled_tasks:
        try:
            task.cancel()
        except Exception as ex:
            logger.warning(ex)


def fswatch_start():
    task = create_permanent_unique_task("ext_fswatch", watch_funding_source)
    scheduled_tasks.append(task)


__all__ = [
    "db",
    "fswatch_ext",
    "fswatch_start",
    "fswatch_static_files",
    "fswatch_stop",
]
