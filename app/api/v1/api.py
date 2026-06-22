from fastapi import APIRouter

from app.api.v1.routers import ai, auth, browser_captures, defects, environment_configs, execution_records, media, projects, scenarios, test_cases, test_plans, test_reports, users, visual_flows, websocket_test_cases

api_router = APIRouter()
api_router.include_router(test_reports.router, prefix="/reports", tags=["Test reports"])
api_router.include_router(execution_records.router, prefix="/execution-records", tags=["Execution records"])
api_router.include_router(defects.router, prefix="/defects", tags=["Defects"])
api_router.include_router(media.router, prefix="/media", tags=["Media"])
api_router.include_router(browser_captures.router, prefix="/browser-captures", tags=["Browser captures"])
api_router.include_router(visual_flows.router, prefix="/flows", tags=["Visual flows"])
api_router.include_router(websocket_test_cases.router, prefix="/websocket-test-cases", tags=["WebSocket test cases"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(environment_configs.router, prefix="/environment-configs", tags=["环境配置"])
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(projects.router, prefix="/projects", tags=["项目权限"])
api_router.include_router(test_cases.router, prefix="/test-cases", tags=["测试用例"])
api_router.include_router(scenarios.router, prefix="/scenarios", tags=["场景组合"])
api_router.include_router(scenarios.run_router, prefix="/scenario-runs", tags=["场景运行"])
api_router.include_router(test_plans.router, prefix="/test-plans", tags=["测试计划"])
api_router.include_router(test_plans.run_router, prefix="/test-plan-runs", tags=["测试计划运行"])
api_router.include_router(users.router, prefix="/users", tags=["用户权限"])
