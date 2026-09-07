"""기능 라우터 자동 등록.

이 패키지 안의 모듈이 모듈 수준 ``router`` 를 정의하면 자동으로 등록된다.
기능 추가 = 이 디렉터리에 파일 하나 추가. ``app/main.py`` 는 건드리지 않는다.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def discover_routers() -> list[tuple[str, APIRouter]]:
    """``(모듈 이름, router)`` 목록을 모듈 이름 순으로 돌려준다.

    정렬하는 이유는 경로 해석 순서를 결정론적으로 만들기 위해서다.
    ``router`` 속성이 없는 모듈은 건너뛴다. 반면 임포트 실패는 **치명적**이다 —
    라우트가 조용히 사라지는 것보다 부팅이 실패하는 편이 낫다.
    """
    found: list[tuple[str, APIRouter]] = []
    for module_info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if module_info.name.startswith("_"):
            continue
        module_name = f"{__name__}.{module_info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            logger.exception("라우터 모듈 임포트 실패: %s", module_name)
            raise
        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            logger.info("%s 에 router 가 없어 건너뜀", module_name)
            continue
        found.append((module_info.name, router))
    return found


def include_all(application: FastAPI) -> list[str]:
    """찾은 라우터를 전부 등록하고 등록된 모듈 이름을 돌려준다."""
    names: list[str] = []
    for name, router in discover_routers():
        application.include_router(router)
        names.append(name)
    logger.info("등록된 라우터: %s", ", ".join(names) or "(없음)")
    return names
