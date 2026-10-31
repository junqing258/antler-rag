class APIError(Exception):
    """已知的 API 失败，由应用中间件统一渲染。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
