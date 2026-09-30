@echo off
cd /d "%~dp0"
cargo run --locked --release
pause
