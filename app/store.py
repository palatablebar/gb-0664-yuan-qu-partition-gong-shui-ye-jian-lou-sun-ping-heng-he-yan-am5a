import sqlite3,json
from contextlib import contextmanager
from app.config import data_dir
from app.errors import reject
@contextmanager
def connect():
    d=data_dir();d.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(d/"records.sqlite",timeout=20)
    c.row_factory=sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,digest TEXT UNIQUE,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    c.execute("CREATE TABLE IF NOT EXISTS tickets (night TEXT PRIMARY KEY,version INTEGER NOT NULL,digest TEXT NOT NULL,body TEXT NOT NULL,updated_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS ticket_versions (night TEXT NOT NULL,version INTEGER NOT NULL,digest TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(night,version))")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
def save(result):
    m=result["manifest"]
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO runs(id,digest,body) VALUES(?,?,?)",(m["run_id"],m["sha256"],json.dumps(result,ensure_ascii=False)))
    return fetch(m["run_id"])
def fetch(run_id):
    with connect() as c:row=c.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
    if row is None:reject("NOT_FOUND","运行不存在")
    data=json.loads(row["body"]);data["revision"]=row["revision"];data["decision"]=row["decision"]
    return data
def history():
    with connect() as c:return [dict(x) for x in c.execute("SELECT id,revision,decision FROM runs ORDER BY rowid DESC LIMIT 100")]
def review(run_id,revision,decision):
    if not isinstance(revision,int) or isinstance(revision,bool) or revision<1:reject("VERSION","修订号须为正整数")
    if decision not in ("通过","退回"):reject("DECISION","复核状态无效")
    with connect() as c:
        changed=c.execute("UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?",(decision,run_id,revision)).rowcount
        if not changed:reject("STALE_VERSION","数据已更新，请重新载入")
    return fetch(run_id)
def publish_ticket(snapshot,digest):
    """一个夜次只有一张处置单。同摘要重跑为空操作；内容变化才递增版本。单事务保证失败不留半版。"""
    import time
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc).isoformat()
    body=json.dumps(snapshot,ensure_ascii=False)
    with connect() as c:
        current=c.execute("SELECT version,digest FROM tickets WHERE night=?",(snapshot["night"],)).fetchone()
        if current is not None and current["digest"]==digest:
            return {"night":snapshot["night"],"version":current["version"],"created":False,"superseded":None}
        version=1 if current is None else current["version"]+1
        c.execute("INSERT OR REPLACE INTO tickets(night,version,digest,body,updated_at) VALUES(?,?,?,?,?)",(snapshot["night"],version,digest,body,now))
        c.execute("INSERT OR REPLACE INTO ticket_versions(night,version,digest,body,created_at) VALUES(?,?,?,?,?)",(snapshot["night"],version,digest,body,now))
        return {"night":snapshot["night"],"version":version,"created":True,"superseded":current["version"] if current else None}
def current_ticket(night):
    with connect() as c:row=c.execute("SELECT * FROM tickets WHERE night=?",(night,)).fetchone()
    if row is None:return None
    data=json.loads(row["body"]);data["version"]=row["version"];return data
def ticket_version(night,version):
    with connect() as c:row=c.execute("SELECT * FROM ticket_versions WHERE night=? AND version=?",(night,version)).fetchone()
    if row is None:reject("NOT_FOUND","该夜次没有此版本")
    data=json.loads(row["body"]);data["version"]=row["version"];return data
def ticket_history(night):
    with connect() as c:return [dict(x) for x in c.execute("SELECT version,digest,created_at FROM ticket_versions WHERE night=? ORDER BY version DESC",(night,))]
def latest_ticket():
    with connect() as c:row=c.execute("SELECT * FROM tickets ORDER BY night DESC LIMIT 1").fetchone()
    if row is None:return None
    data=json.loads(row["body"]);data["version"]=row["version"];return data
def ticket_nights():
    with connect() as c:return [x["night"] for x in c.execute("SELECT night FROM tickets ORDER BY night DESC")]
