from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.db import SessionLocal
from app.routers import events
from app.routers import list as list_router
from app.seed import ensure_seed
from app.templating import STATIC_DIR, static_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as session:
        ensure_seed(session)
    yield


app = FastAPI(title="Hungry Hippos", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        if "v" in request.query_params:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(list_router.router)
app.include_router(events.router)


@app.get("/")
def index():
    return RedirectResponse("/list", status_code=302)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/sw.js")
def service_worker():
    body = (STATIC_DIR / "sw.js").read_text()
    return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def web_manifest():
    return JSONResponse(
        {
            "name": "Hungry Hippos",
            "short_name": "Hippos",
            "start_url": "/list",
            "scope": "/",
            "display": "standalone",
            "background_color": "#FFFFFF",
            "theme_color": "#10291C",
            "icons": [
                {"src": static_url("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                {"src": static_url("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
                {"src": static_url("icons/maskable-512.png"), "sizes": "512x512", "type": "image/png",
                 "purpose": "maskable"},
            ],
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )
