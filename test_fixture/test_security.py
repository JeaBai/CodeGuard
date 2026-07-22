"""安全红线测试文件"""
import os
import subprocess

# [BLOCK] 硬编码密码
DB_PASSWORD = "admin123"

# [BLOCK] SQL注入风险 - 字符串拼接
def get_user(username):
    query = "SELECT * FROM users WHERE name = '%s'" % username
    return query

# [BLOCK] eval 调用
def execute_dynamic(code_str):
    result = eval(code_str)
    return result

# [BLOCK] exec 调用
def run_code(code_str):
    exec(code_str)

# [BLOCK] os.system 命令注入
def run_command(cmd):
    os.system(cmd)

# [BLOCK] 日志泄露密码
import logging
logging.debug("User login with password admin123")
