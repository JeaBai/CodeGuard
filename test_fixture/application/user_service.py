"""应用层：用户服务 - 应只依赖 Domain 层"""
from domain.user_entity import UserEntity


class UserService:
    """正常的应用层服务"""
    
    def get_user(self, user_id: int) -> UserEntity:
        return UserEntity("test", "test@example.com")


# ============ 违规代码块：应用层直接依赖基础设施 ============
from infrastructure.database import DatabaseConnection  # [WARN] 架构警告


class AdminService:
    """管理员服务 - 直接依赖基础设施层具体实现"""
    
    def __init__(self):
        self.db = DatabaseConnection("postgres://localhost")  # [WARN] 架构警告
    
    def delete_all_users(self):
        self.db.execute("DELETE FROM users")  # [WARN] 架构警告
