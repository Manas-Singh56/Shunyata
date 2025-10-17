@echo off
echo ============================================
echo 🚀 Starting Shunyata Central Judge Server
echo ============================================

:: Find local IP address (works for Wi-Fi / Hotspot)
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /R "IPv4.*192\."') do (
    set ip=%%a
)
set ip=%ip: =%

if "%ip%"=="" (
    echo ❌ Could not detect local IP automatically.
    echo Please check your Wi-Fi connection.
    pause
    exit /b
)

echo ✅ Detected Local IP: %ip%
echo --------------------------------------------
echo 📡 Other participants should run this command:
echo python cea.py --server-ip %ip% --server-port 5000
echo --------------------------------------------
echo 🔗 They can access contest at: http://127.0.0.1:8000
echo --------------------------------------------

:: Optional firewall rule to allow incoming connections
echo ⚙️ Ensuring firewall allows port 5000...
netsh advfirewall firewall add rule name="ShunyataCJS" dir=in action=allow protocol=TCP localport=5000 >nul 2>&1

:: Start the server
echo 🖥️ Launching Central Judge Server...
python main.py

pause
