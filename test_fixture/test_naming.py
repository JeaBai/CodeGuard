"""命名一致性测试 - 同一实体使用不同动词前缀"""

def get_user_by_id(user_id: int):
    return {"id": user_id}

def fetch_user_by_id(user_id: int):
    return {"id": user_id}

def retrieve_user_by_id(user_id: int):
    return {"id": user_id}

def find_user_by_id(user_id: int):
    return {"id": user_id}
