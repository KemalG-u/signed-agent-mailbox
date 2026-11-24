#!/usr/bin/env bash
# Tek komutla uçtan uca sınama. Kullanım: ./uctan-uca.sh [--hizli] [--arac AD ...]
# Python'u kendisi bulur (Git Bash'te yalın `python` olmayabilir): ARAC_PYTHON, python, python3, py -3, %LOCALAPPDATA% altındaki Python312.
cd "$(dirname "$0")" || exit 2
PYBIN=""
for aday in "${ARAC_PYTHON:-}" python python3 "${LOCALAPPDATA:-}/Programs/Python/Python312/python.exe"; do
  [ -n "$aday" ] || continue
  if command -v "$aday" >/dev/null 2>&1 && "$aday" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
    PYBIN="$aday"; break
  fi
done
if [ -z "$PYBIN" ] && command -v py >/dev/null 2>&1 && py -3 -c "pass" 2>/dev/null; then
  exec py -3 -X utf8 uctan-uca.py "$@"
fi
[ -n "$PYBIN" ] || { echo "python 3.9+ bulunamadı (ARAC_PYTHON ile yol verin)" >&2; exit 2; }
exec "$PYBIN" -X utf8 uctan-uca.py "$@"
