import csv,io,json
from decimal import Decimal
from datetime import datetime,timedelta,timezone
from app.config import DISPOSITION_VERSION
from app.errors import reject
CST=timezone(timedelta(hours=8))
TIER={"倒挂":0,"漏损":0,"待观察":1,"通过":2}
ACTION={"漏损":"立即处置","倒挂":"复核计量方向","待观察":"补测读数或复核宽误差表","通过":"无需处置"}
CERTAINTY={"漏损":"已确认","倒挂":"已确认","待观察":"待确认","通过":"已确认"}
def night_key(at):
    local=datetime.fromisoformat(at).astimezone(CST)
    if 0<=local.hour<5:return local.date().isoformat()
    return None
def pick_night(rows):
    nights=sorted({key for row in rows if (key:=night_key(row["at"]))})
    if not nights:reject("NIGHT","没有夜间读数，无法生成处置单")
    return nights[-1]
def basis(item,threshold):
    threshold=Decimal(str(threshold))
    lower=Decimal(item["lower"]);upper=Decimal(item["upper"]);residual=Decimal(item["residual"])
    if item["status"]=="漏损":return f"下界 {item['lower']} > 阈值 {format(threshold.normalize(),'f')}，漏损已确认"
    if item["status"]=="倒挂":return f"上界 {item['upper']} < 0，流入不足以覆盖流出，计量或归属有误"
    if item["status"]=="待观察":return f"残差 {item['residual']} > 阈值，但区间 [{item['lower']}, {item['upper']}] 未排除阈值，尚不确定"
    return f"残差 {item['residual']} 未超阈值，区间 [{item['lower']}, {item['upper']}] 无异常"
def rank(items):
    """确定性优先于水量：已确认的分区先派单，待确认分区排在确认之后。"""
    def key(item):
        tier=TIER[item["status"]]
        magnitude=abs(Decimal(item["residual"])) if item["status"]=="倒挂" else Decimal(item["residual"])
        return (tier,-magnitude,item["zone"])
    ordered=sorted(items,key=key)
    for index,item in enumerate(ordered,1):item["order"]=index
    return ordered
def headline(items):
    confirmed=[x for x in items if x["status"] in {"漏损","倒挂"}]
    watch=[x for x in items if x["status"]=="待观察"]
    if confirmed:
        first=confirmed[0]
        rest="、".join(x["zone"] for x in confirmed[1:])
        tail=f"，其后 {rest}" if rest else ""
        note=f"；{len(watch)} 个分区待确认，需补读数后再评估" if watch else ""
        return f"先查 {first['zone']}（{first['status']}已确认，残差 {first['residual']} m³）{tail}{note}"
    if watch:
        return f"当晚无已确认漏损；{len(watch)} 个分区区间跨阈值，先补测 {'、'.join(x['zone'] for x in watch)} 而不按水量大小派单"
    return "当晚各分区均在误差界内，无需处置"
def readings(rows,zone):
    detail=[]
    for row in rows:
        if zone==row["to_zone"]:direction="流入"
        elif zone==row["from_zone"]:direction="流出"
        else:continue
        detail.append({"line":row["line"],"record_id":row["record_id"],"meter":row["meter"],"kind":row["kind"],"direction":direction,
            "from_zone":row["from_zone"],"to_zone":row["to_zone"],"at":row["at"],"value":row["value"],"unit":row["unit"],
            "value_m3":row["value_m3"],"error_pct":row["error_pct"]})
    return sorted(detail,key=lambda x:(x["line"],x["record_id"]))
def transfers(rows,zone):
    out=[{"meter":r["meter"],"to_zone":r["to_zone"],"value_m3":r["value_m3"],"line":r["line"]} for r in rows if r["kind"]=="transfer" and r["from_zone"]==zone]
    incoming=[{"meter":r["meter"],"from_zone":r["from_zone"],"value_m3":r["value_m3"],"line":r["line"]} for r in rows if r["kind"]=="transfer" and r["to_zone"]==zone]
    return sorted(out,key=lambda x:(x["to_zone"],x["meter"])),sorted(incoming,key=lambda x:(x["from_zone"],x["meter"]))
def destination_text(out,incoming):
    parts=[f"→ {x['to_zone']} {x['value_m3']} m³（{x['meter']}，行 {x['line']}）" for x in out]
    parts+= [f"← {x['from_zone']} {x['value_m3']} m³（{x['meter']}，行 {x['line']}）" for x in incoming]
    return "；".join(parts) if parts else "无跨区转供"
def digest_of(snapshot):
    """披露摘要只覆盖当晚结论与所用读数。同一晚相同结论重跑得到同一摘要，不新增处置单；
    读数或结论变化才产生新版本。运行号不参与摘要，避免同一结论因重跑换号而重复开单。"""
    import hashlib
    core={"night":snapshot["night"],"threshold":snapshot["threshold"],"rule":DISPOSITION_VERSION,
        "zones":[{"zone":z["zone"],"status":z["status"],"residual":z["residual"],"lower":z["lower"],"upper":z["upper"],
        "readings":[[r["line"],r["record_id"],r["meter"],r["value_m3"],r["error_pct"]] for r in z["readings"]]} for z in snapshot["zones"]]}
    material=json.dumps(core,sort_keys=True,ensure_ascii=False,separators=(",",":"))
    return hashlib.sha256(material.encode()).hexdigest()
def evidence_csv(ticket):
    buffer=io.StringIO();writer=csv.writer(buffer)
    writer.writerow(["夜次","版本","顺序","类别","分区","结论","可信度","残差","下界","上界","来源行","表号","原始读数","跨区转供去向","依据"])
    for zone in ticket["zones"]:
        writer.writerow([ticket["night"],ticket["version"],zone["order"],"结论",zone["zone"],zone["status"],zone["certainty"],
            zone["residual"],zone["lower"],zone["upper"],",".join(str(x["line"]) for x in zone["readings"]),"",
            "",zone["transfer_text"],zone["basis"]])
        for reading in zone["readings"]:
            writer.writerow([ticket["night"],ticket["version"],zone["order"],"读数",zone["zone"],reading["kind"],reading["direction"],
                reading["value_m3"],"","",reading["line"],reading["meter"],f"{reading['value']} {reading['unit']}",reading["to_zone"] if reading["direction"]=="流出" else reading["from_zone"],""])
    return "﻿"+buffer.getvalue()
