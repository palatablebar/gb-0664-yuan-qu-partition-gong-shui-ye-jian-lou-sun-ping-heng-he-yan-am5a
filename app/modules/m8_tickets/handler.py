from fastapi import APIRouter
from app.modules.m8_tickets.service import run
from app.errors import DomainError,http_error
from app.store import current_ticket,ticket_version,ticket_history,ticket_nights
from .rules import evidence_csv
router=APIRouter()

def _resolve(night,version):
    if version is not None:return ticket_version(night,version)
    data=current_ticket(night)
    if data is None:raise DomainError("NOT_FOUND","该夜次没有处置单")
    return data

def _with_context(ticket):
    ticket["history"]=ticket_history(ticket["night"])
    ticket["nights"]=ticket_nights()
    return ticket

@router.get("/api/tickets")
def evaluate(sample:str="dirty",threshold:str="5",night:str|None=None,version:int|None=None):
    try:
        if night is not None:return _with_context(_resolve(night,version))
        return run({"sample":sample,"params":{"threshold":threshold}})
    except DomainError as exc:raise http_error(exc)

@router.get("/api/tickets/nights")
def nights():return {"nights":ticket_nights()}

@router.get("/api/tickets/{night}/evidence.csv")
def evidence(night:str,version:int|None=None):
    from fastapi.responses import Response
    try:
        ticket=_resolve(night,version)
        return Response(evidence_csv(ticket),media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":f'attachment; filename=ticket-{night}-v{ticket["version"]}.csv'})
    except DomainError as exc:raise http_error(exc)

@router.get("/api/tickets/{night}/history")
def versions(night:str):
    with_history=ticket_history(night)
    if not with_history:raise http_error(DomainError("NOT_FOUND","该夜次没有处置单"))
    return {"night":night,"versions":with_history}
