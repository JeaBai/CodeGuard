# Python 大型 AI代码 — 500+行
# 大量重复模式 + 安全违规 + 高CC + 架构违规
import os,sqlite3,smtplib,subprocess
SMTP_PASS="mail123"
DB_URL="mysql://root:admin@localhost/db"
API_SECRET="sk-large-test"

# 重复模式1 — 发送邮件 (10个变体)
def send_welcome(e):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e","welcome");s.quit()
def send_reset(e,t):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e",f"reset:{t}");s.quit()
def send_notify(e,m):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e",m);s.quit()
def send_alert(e,a):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e",a);s.quit()
def send_report(e,r):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e",r);s.quit()
def send_invoice(e,i):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e",i);s.quit()
def send_reminder(e):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e","reminder");s.quit()
def send_bill(e,b):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e",b);s.quit()
def send_receipt(e,r):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e",r);s.quit()
def send_confirmation(e):s=smtplib.SMTP("smtp.test.com",587);s.login("a",SMTP_PASS);s.sendmail("a","e","confirmed");s.quit()

# 高CC函数
def mega_process(d,c,f,t,m,p):
    r=0
    if d:
        if d>0:
            if d>100:
                if c=="gold":
                    if f:
                        if t:
                            if m=="express":
                                r=d*0.5
                            elif m=="overnight":
                                r=d*0.3
                            else:
                                r=d*0.7
            elif d>50:
                if c=="silver":
                    r=d*0.6
                else:
                    r=d*0.8
    if p:
        r-=p
    if r<0:r=0
    return r

# SQL注入
def query_user(n):c=sqlite3.connect("x").cursor();c.execute("SELECT * FROM u WHERE n='%s'"%n);return c.fetchone()
def query_order(i):c=sqlite3.connect("x").cursor();c.execute("SELECT * FROM o WHERE i='%s'"%i);return c.fetchone()
def query_product(p):c=sqlite3.connect("x").cursor();c.execute("SELECT * FROM p WHERE n='%s'"%p);return c.fetchone()

# 空异常处理
def risky_operation(x):
    try:os.system(x)
    except:pass
    try:eval(x)
    except:pass
    try:subprocess.call(x)
    except:pass

# 日志泄露
def debug_info(u,p):
    print(f"User {u} password: {p}")
    print(f"API key: {API_SECRET}")
    print(f"DB: {DB_URL}")
