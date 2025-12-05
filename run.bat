@echo off
echo ============================================================
echo PromptRig - Starting Application / アプリケーションを起動中
echo ============================================================
echo.

if not exist venv (
    echo ERROR: Virtual environment not found
    echo Please run setup.bat first
    echo.
    echo エラー: 仮想環境が見つかりません
    echo 先にsetup.batを実行してください
    pause
    exit /b 1
)

echo Activating virtual environment / 仮想環境を有効化中...
call venv\Scripts\activate

echo Starting server on http://localhost:9200
echo サーバーを起動しています: http://localhost:9200
echo.
echo Press Ctrl+C to stop / Ctrl+Cで停止
echo ============================================================
echo.

python main.py

pause
