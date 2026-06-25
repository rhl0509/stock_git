# templates_config.py — FastAPI Jinja2 템플릿 공유 설정
from pathlib import Path
from fastapi import Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse

_TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

# React SPA 빌드가 존재하면 모든 페이지 라우트를 SPA로 서빙
_SPA_INDEX = Path(__file__).parent / "static" / "spa" / "index.html"
SPA_MODE = _SPA_INDEX.exists()


class _RequestWrapper:
    """Starlette Request에 .path 속성을 추가해 Flask 템플릿 호환성 유지."""
    __slots__ = ("_req", "path")

    def __init__(self, req: Request):
        object.__setattr__(self, "_req", req)
        object.__setattr__(self, "path", req.url.path)

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_req"), name)


def render(request: Request, template: str, ctx: dict | None = None):
    """render_template() 대체 헬퍼.
    SPA 빌드가 있으면 React index.html을 반환, 없으면 Jinja2 렌더링.
    """
    if SPA_MODE:
        return FileResponse(str(_SPA_INDEX))
    context = ctx or {}
    context["request"] = _RequestWrapper(request)
    context.setdefault("session", request.session)
    return templates.TemplateResponse(request, template, context)
