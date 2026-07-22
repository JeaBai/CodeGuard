"""基础设施层：数据库连接 - 应实现 Domain 层接口"""

class DatabaseConnection:
    def __init__(self, connection_string: str):
        self.conn_string = connection_string
    
    def execute(self, query: str):
        """执行 SQL - 正常方法"""
        pass
