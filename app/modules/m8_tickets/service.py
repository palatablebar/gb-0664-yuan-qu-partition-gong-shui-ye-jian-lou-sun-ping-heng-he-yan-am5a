from decimal import Decimal
from app.errors import reject
from app.modules.m6_reconcile.rules import classify
from app.modules.m4_calculate.rules import balances
from app.store import publish_ticket,current_ticket,ticket_history,ticket_nights
from .rules import ACTION,CERTAINTY,night_key,pick_night,basis,rank,headline,readings,transfers,destination_text,digest_of

def nights_in(result):
    return sorted({key for row in result["rows"] if (key:=night_key(row["at"]))})

def build(result,threshold,night=None):
    """按夜次切片重算三个分区。跨夜合计会掩盖单晚漏损，也会把不同晚的证据混在一张单上。"""
    available=nights_in(result)
    night=night or (available[-1] if available else None)
    if night is None:reject("NIGHT","没有夜间读数，无法生成处置单")
    if night not in available:reject("NIGHT","该夜次没有可采信的夜间读数")
    rows=[row for row in result["rows"] if night_key(row["at"])==night]
    items=[]
    for item in balances(rows,result["zones"]):
        item["status"]=classify(item,threshold)
        out,incoming=transfers(rows,item["zone"])
        items.append({"zone":item["zone"],
            "inflow":item["inflow"],"outflow":item["outflow"],"sale":item["sale"],"authorized":item["authorized"],
            "uncertainty":item["uncertainty"],"residual":item["residual"],"lower":item["lower"],"upper":item["upper"],
            "status":item["status"],"certainty":CERTAINTY[item["status"]],"action":ACTION[item["status"]],
            "basis":basis(item,threshold),"readings":readings(rows,item["zone"]),
            "transfer_out":out,"transfer_in":incoming,"transfer_text":destination_text(out,incoming)})
    ordered=rank(items)
    reason={"漏损":"漏损已确认","倒挂":"方向冲突已确认","待观察":"区间未收窄","通过":"无异常"}
    for item in ordered:item["basis"]=item["basis"]+f"；处置顺序第 {item['order']}，因为{reason[item['status']]}"
    snapshot={"night":night,"threshold":format(Decimal(str(threshold)).normalize(),"f"),
        "rule_version":result["manifest"]["rule_version"],"run_id":result["manifest"]["run_id"],
        "headline":headline(ordered),"zones":ordered,"line_count":len(rows)}
    snapshot["digest"]=digest_of(snapshot)
    return snapshot

def attach(result,threshold=None,night=None):
    snapshot=build(result,threshold or "5",night)
    publication=publish_ticket(snapshot,snapshot["digest"])
    stored=current_ticket(snapshot["night"])
    stored["history"]=ticket_history(snapshot["night"])
    stored.update({"created":publication["created"],"superseded":publication["superseded"],
        "run_id":snapshot["run_id"],"nights":nights_in(result)})
    result["ticket"]=stored
    return result

def run(options=None):
    from app.modules.m7_batches.service import run as previous
    options=dict(options or {})
    night=options.pop("night",None)
    result=previous(options)
    threshold=result.get("manifest",{}).get("params",{}).get("threshold","5")
    return attach(result,threshold,night)
