@echo off
set "PROJECT_DIR=%~dp0"
set "LOCAL_SITE=http://127.0.0.1:5000"
set "LOCAL_LISTINGS_API=http://127.0.0.1:5000/api/listings"
set "LOCAL_STATUS_API=http://127.0.0.1:5000/api/listings/status"

start "TCG VIP App Local" powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location '%PROJECT_DIR%'; $env:SITE_URL='%LOCAL_SITE%'; $env:MOBILE_APP_URL='%LOCAL_SITE%'; $env:APP_API_URL='%LOCAL_LISTINGS_API%'; $env:APP_API_STATUS_URL='%LOCAL_STATUS_API%'; $env:APP_API_ENABLED='true'; python vip_app\manage.py run"
start "TCG Pricing Worker" powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location '%PROJECT_DIR%'; $env:SITE_URL='%LOCAL_SITE%'; $env:MOBILE_APP_URL='%LOCAL_SITE%'; $env:APP_API_URL='%LOCAL_LISTINGS_API%'; $env:APP_API_STATUS_URL='%LOCAL_STATUS_API%'; $env:APP_API_ENABLED='true'; python pricing_worker.py"
start "TCG Gone Alerts Worker" powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location '%PROJECT_DIR%'; $env:SITE_URL='%LOCAL_SITE%'; $env:MOBILE_APP_URL='%LOCAL_SITE%'; $env:APP_API_URL='%LOCAL_LISTINGS_API%'; $env:APP_API_STATUS_URL='%LOCAL_STATUS_API%'; $env:APP_API_ENABLED='true'; $env:ENABLE_FREE_GONE_ALERTS='true'; python gone_alert_worker.py"
start "TCG Bot Local" cmd /k "cd /d %PROJECT_DIR% && timeout /t 4 /nobreak >nul && set SITE_URL=%LOCAL_SITE% && set MOBILE_APP_URL=%LOCAL_SITE% && set APP_API_URL=%LOCAL_LISTINGS_API% && set APP_API_STATUS_URL=%LOCAL_STATUS_API% && set APP_API_ENABLED=true && set ENABLE_WALLAPOP=true && set WALLAPOP_INLINE_IN_MAIN_BOT=true && set WALLAPOP_SEND_TELEGRAM=false && set WALLAPOP_MAX_ITEMS_PER_RUN=6 && set WALLAPOP_HEADLESS=true && set WALLAPOP_DELAY_MIN_SECONDS=2 && set WALLAPOP_DELAY_MAX_SECONDS=5 && python vinted_olx_bot.py"

exit /b 0
