from fastapi import APIRouter,Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.config import TITLE,MODULES,RULE_VERSION
from app.modules.m7_batches.service import run
from app.modules.m8_tickets.service import attach
from app.store import fetch,current_ticket,ticket_version,ticket_history
from app.errors import DomainError,http_error
router=APIRouter();templates=Jinja2Templates(directory="app/templates")
@router.get("/")
def home():return RedirectResponse("/tickets")
def ticket_view(run_id,night,version):
    base=fetch(run_id) if run_id else run({"sample":"dirty"})
    threshold=base.get("manifest",{}).get("params",{}).get("threshold","5")
    data=attach(base,threshold,night)
    ticket=data["ticket"]
    if version is not None and version!=ticket["version"]:
        historical=ticket_version(ticket["night"],version)
        historical.update({"history":ticket_history(ticket["night"]),"nights":ticket["nights"],
            "created":False,"superseded":None,"is_historical":True,"run_id":data["manifest"]["run_id"]})
        data=dict(data);data["ticket"]=historical
    return data
def page(request:Request,slug:str,run_id:str|None=None,night:str|None=None,version:int|None=None):
    if slug=="tickets":data=ticket_view(run_id,night,version)
    else:
        if night or version is not None:raise http_error(DomainError("PARAMETER","只有夜间处置页支持夜次与版本参数"))
        data=fetch(run_id) if run_id else run({"sample":"dirty"})
    return templates.TemplateResponse(request=request,name=slug+".html",context={"data":data,"title":TITLE,"modules":MODULES,"slug":slug,"page_title":dict(MODULES)[slug],"version":RULE_VERSION})
for slug,label in MODULES:
    def view(request:Request,run_id:str|None=None,night:str|None=None,version:int|None=None,_slug=slug):return page(request,_slug,run_id,night,version)
    router.add_api_route("/"+slug,view,methods=["GET"],include_in_schema=False)
