from fastapi import APIRouter

from app.api.v1.routers import ai, auth, environment_configs, projects, test_cases, users, visual_flows, websocket_test_cases

api_router = APIRouter()
api_router.include_router(visual_flows.router, prefix="/flows", tags=["Visual flows"])
api_router.include_router(websocket_test_cases.router, prefix="/websocket-test-cases", tags=["WebSocket test cases"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(environment_configs.router, prefix="/environment-configs", tags=["环境配置"])
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(projects.router, prefix="/projects", tags=["项目权限"])
api_router.include_router(test_cases.router, prefix="/test-cases", tags=["测试用例"])
api_router.include_router(users.router, prefix="/users", tags=["用户权限"])
