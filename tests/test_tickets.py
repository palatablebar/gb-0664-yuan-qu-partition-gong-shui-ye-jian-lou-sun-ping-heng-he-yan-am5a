import pytest
from decimal import Decimal
from app.modules.m8_tickets.service import run
from app.modules.m8_tickets.rules import rank,headline,night_key
from app.store import current_ticket,ticket_version,ticket_history,publish_ticket,connect
from app.errors import DomainError
HEADER="record_id,at,meter,from_zone,to_zone,kind,value,unit,error_pct"
def csv(*rows):return "\n".join([HEADER,*rows])
def night10(rows):return {"text":csv(*rows),"params":{"threshold":"20"}}

# A 区供水误差很宽，残差 100 但区间 [0,200] 跨阈值；B 区残差仅 25 却已确认漏损。
WIDE=[ "1-IN-A,2026-11-10T02:00:00+08:00,IN-A,EXT,A,supply,1000,m3,10",
 "1-AB,2026-11-10T02:00:00+08:00,AB,A,B,transfer,300,m3,0",
 "1-SA,2026-11-10T02:00:00+08:00,SA,A,OUT,sale,500,m3,0",
 "1-UA,2026-11-10T02:00:00+08:00,UA,A,OUT,authorized,100,m3,0",
 "1-SB,2026-11-10T02:00:00+08:00,SB,B,OUT,sale,270,m3,0",
 "1-UB,2026-11-10T02:00:00+08:00,UB,B,OUT,authorized,5,m3,0"]

def test_one_ticket_per_night(dirty):
    a=run(dirty);b=run(dirty)
    assert a["ticket"]["night"]=="2026-11-06"
    assert b["ticket"]["version"]==1 and b["ticket"]["created"] is False
    assert len(b["ticket"]["history"])==1

def test_certainty_before_volume():
    t=run(night10(WIDE))["ticket"]
    zones={z["zone"]:z for z in t["zones"]}
    assert Decimal(zones["A"]["residual"])>Decimal(zones["B"]["residual"])
    assert zones["B"]["order"]<zones["A"]["order"]
    assert zones["B"]["certainty"]=="已确认" and zones["A"]["certainty"]=="待确认"
    assert t["headline"].startswith("先查 B")

def test_zone_detail_complete(dirty):
    t=run(dirty)["ticket"];zone=next(z for z in t["zones"] if z["zone"]=="A")
    assert all(k in zone for k in ("residual","lower","upper","uncertainty"))
    assert Decimal(zone["lower"])<=Decimal(zone["residual"])<=Decimal(zone["upper"])
    assert zone["readings"],"必须带原始读数"
    assert all(r["line"] and r["record_id"] and r["value"] and r["unit"] for r in zone["readings"])
    assert any("→" in part and "行" in part for part in zone["transfer_text"].split("；"))

def test_transfer_destination(dirty):
    t=run(dirty)["ticket"];zone=next(z for z in t["zones"] if z["zone"]=="A")
    out={x["to_zone"] for x in zone["transfer_out"]}
    assert out=={"B","C"}
    bb=next(z for z in t["zones"] if z["zone"]=="B")
    assert "← A" in bb["transfer_text"]

def test_readings_stay_in_their_night(clean):
    t=run(clean)["ticket"]
    assert t["night"]=="2026-11-06"
    assert all(r["at"].startswith("2026-11-05T18") for z in t["zones"] for r in z["readings"])

def test_threshold_change_creates_new_version(dirty):
    a=run(dirty)
    b=run({"sample":"dirty","params":{"threshold":"100"}})
    assert b["ticket"]["version"]==2 and b["ticket"]["superseded"]==1
    old=ticket_version("2026-11-06",1)
    assert any(z["status"]=="漏损" for z in old["zones"]),"旧版结论仍可追回"

def test_failure_keeps_old_version(dirty):
    run(dirty)
    with pytest.raises(DomainError):run({"text":"wrong"})
    kept=current_ticket("2026-11-06")
    assert kept["version"]==1 and len(ticket_history("2026-11-06"))==1

def test_publish_is_transactional(dirty):
    run(dirty)
    snapshot=current_ticket("2026-11-06");snapshot["threshold"]="99";snapshot["digest"]="manual"
    with connect() as c:
        c.execute("CREATE TRIGGER boom BEFORE INSERT ON ticket_versions BEGIN SELECT RAISE(ABORT,'boom'); END")
    with pytest.raises(Exception):publish_ticket(snapshot,"manual")
    with connect() as c:c.execute("DROP TRIGGER boom")
    kept=current_ticket("2026-11-06")
    assert kept["version"]==1 and kept["threshold"]!="99", "中途失败不得留下半版"

def test_night_boundary():
    assert night_key("2026-11-10T20:59:59+00:00")=="2026-11-11"
    assert night_key("2026-11-10T21:00:00+00:00") is None

def test_rank_stable():
    items=[{"zone":"C","status":"待观察","residual":"500"},{"zone":"A","status":"通过","residual":"1"},
           {"zone":"B","status":"漏损","residual":"5"},{"zone":"D","status":"倒挂","residual":"-30"}]
    assert [x["zone"] for x in rank(items)]==["D","B","C","A"]
    assert "无需处置" in headline([{"zone":"A","status":"通过","residual":"1"}])

def test_no_night_rejected():
    with pytest.raises(DomainError,match="夜间"):run({"text":csv("1-IN-A,2026-11-10T06:00:00+08:00,IN-A,EXT,A,supply,10,m3,1")})

def test_each_night_own_ticket(dirty):
    from app.modules.m8_tickets.service import run as ticket_run
    a=ticket_run({"sample":"dirty","night":"2026-11-03"})
    b=ticket_run({"sample":"dirty","night":"2026-11-04"})
    assert a["ticket"]["night"]=="2026-11-03" and b["ticket"]["night"]=="2026-11-04"
    assert all(z["readings"] for z in a["ticket"]["zones"])
    assert {r["at"][:13] for z in a["ticket"]["zones"] for r in z["readings"]}=={"2026-11-02T18"}
    assert {r["at"][:13] for z in b["ticket"]["zones"] for r in z["readings"]}=={"2026-11-03T18"}
    assert a["ticket"]["version"]==1 and b["ticket"]["version"]==1

def test_unknown_night_rejected(dirty):
    with pytest.raises(DomainError,match="夜次"):run({"sample":"dirty","night":"2020-01-01"})
