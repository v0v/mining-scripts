@echo off
:start
    xmrig.exe  -a rx/wow -o stanvps.ddns.net:8120 -u STAN-PROXY.0x49_3f09--2660k ^
        --http-port 37329 --http-no-restricted --http-access-token auth
goto start
pause