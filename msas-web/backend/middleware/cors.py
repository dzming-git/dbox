# CORS跨域配置
from flask_cors import CORS

def setup_cors(app):
    """配置CORS"""
    CORS(app, resources={
        r"/api/*": {
            "origins": ["http://localhost:5173", "http://127.0.0.1:5173", "http://0.0.0.0:5173",
                       "http://localhost:3000", "http://localhost:8080"],  # Vue开发服务器
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True,
            "expose_headers": ["Content-Type", "Authorization"]
        }
    })
    return app
