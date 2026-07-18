"""
Dashboard HTML routes. Renders Jinja2 templates; all data fetching/mutation
happens client-side via fetch() calls to /api/* (see routes/api.py + static/app.js).
"""
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
async def root(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request, "active_page": "settings"})


@router.get("/dashboard")
async def dashboard_redirect(request: Request):
    return templates.TemplateResponse("campaigns.html", {"request": request, "active_page": "campaigns"})


@router.get("/dashboard/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request, "active_page": "settings"})


@router.get("/dashboard/campaigns")
async def campaigns_page(request: Request):
    return templates.TemplateResponse("campaigns.html", {"request": request, "active_page": "campaigns"})
