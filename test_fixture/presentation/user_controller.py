"""表现层：用户控制器 - 可依赖 Application 和 Domain"""
from domain.user_entity import UserEntity


class UserController:
    """正常的控制器"""
    
    def get_profile(self, user_id: int):
        return {"user": user_id, "status": "ok"}
