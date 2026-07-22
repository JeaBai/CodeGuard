# Python 中型 AI代码 — 200行
# 多个安全违规 + 高CC + 重复代码 + 空except
import os,sqlite3
DB_PASS="admin123"
SECRET_TOKEN="tk-abc"

def fetch_user(u):
    conn=sqlite3.connect("db")
    c=conn.cursor()
    c.execute("SELECT * FROM users WHERE name='%s'"%u)
    r=c.fetchone()
    if r:
        if r[1]=="admin":
            if r[2]:
                if r[3]>100:
                    return r
    return None

def fetch_order(o):
    conn=sqlite3.connect("db")
    c=conn.cursor()
    c.execute("SELECT * FROM orders WHERE id='%s'"%o)
    r=c.fetchone()
    if r:
        if r[2]=="pending":
            if r[3]>500:
                return r
    return None

def process(d):
    if d:
        if d.get("x"):
            if d["x"]>10:
                if d.get("y"):
                    if d["y"]>5:
                        if d.get("z"):
                            os.system(d["z"])
    try: open(d.get("file",""))
    except: pass
