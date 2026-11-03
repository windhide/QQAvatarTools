@echo off
rem 一键构建 QQAvatarTools.exe（产物在 dist\）
cd /d "%~dp0"
pip install pillow qrcode pyinstaller || goto :err
python tools\download_payload.py || goto :err
pyinstaller --onefile --uac-admin --name QQAvatarTools ^
  --add-data "static;static" --add-data "payload\napcat_shell.zip;." ^
  --clean --noconfirm app.py || goto :err
echo.
echo 构建完成：dist\QQAvatarTools.exe
pause
exit /b 0
:err
echo 构建失败
pause
exit /b 1
