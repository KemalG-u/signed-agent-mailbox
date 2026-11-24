#!/usr/bin/env bash
# kutu icinde (HOME gecici, /mnt yok, --ag ile genel IPv4 acik) agmsg izole uctan uca denemesi
set -u
START="$PWD"
OUT="${KUTU_CIKTI:-$PWD/cikti}"; mkdir -p "$OUT"; LOG="$OUT/agmsg-e2e.log"
exec > >(tee "$LOG") 2>&1
step(){ echo; echo "=== $*"; }
run(){ echo "\$ $*"; "$@"; local rc=$?; echo "[cikis=$rc]"; return $rc; }

step "0. on kontrol: yalitim (kurulumdan once)"
echo "HOME=$HOME"; id
ls /mnt/c 2>&1 | head -1; ls -A /mnt | wc -l | sed 's/^/mnt girdi sayisi: /'
grep -cE "drvfs|9p" /proc/mounts | sed 's/^/9p satir: /'; grep -E "drvfs|aname=[CDE]" /proc/mounts || echo "(drvfs/C-D-E baglama yok)"
ls -A /usr/lib/wsl/drivers | wc -l | sed 's/^/wsl drivers girdi: /'
echo "arayuzler:"; awk 'NR>2{print $1}' /proc/net/dev | tr '\n' ' '; echo

step "1. sqlite3 (kutuda yok): Ubuntu noble-updates .deb, SHA256 dizinden dogrula, cikar"
mkdir -p "$HOME/tools" && cd "$HOME/tools" || exit 90
curl -fsS -m 90 -o Packages.gz https://archive.ubuntu.com/ubuntu/dists/noble-updates/main/binary-amd64/Packages.gz || { echo "FAIL index indirilemedi"; exit 91; }
python3 - <<'PY' > pkg.txt
import gzip
for blok in gzip.open("Packages.gz","rt",encoding="utf-8").read().split("\n\n"):
    d=dict(l.split(": ",1) for l in blok.splitlines() if ": " in l and not l.startswith(" "))
    if d.get("Package")=="sqlite3": print(d["Version"],d["Filename"],d["SHA256"])
PY
cat pkg.txt
read -r VER FN SHA < pkg.txt
curl -fsS -m 120 -o sqlite3.deb "https://archive.ubuntu.com/ubuntu/$FN" || { echo "FAIL deb indirilemedi"; exit 92; }
echo "$SHA  sqlite3.deb" | sha256sum -c - || { echo "FAIL sha256"; exit 93; }
dpkg-deb -x sqlite3.deb root && export PATH="$HOME/tools/root/usr/bin:$PATH"
sqlite3 --version

step "2. agmsg kopyasi (girdi) -> kurulum, HOME disina yazma yok"
SRC="$START/agmsg"
echo "SRC=$SRC"; cat "$SRC/VERSION"
export AGMSG_INSTALL_HOME="$HOME/inst" AGMSG_HOME="$HOME/agmsg-state" CODEX_HOME="$HOME/codexhome" AGMSG_BIN_DIR="$HOME/inst/bin"
mkdir -p "$AGMSG_INSTALL_HOME" "$AGMSG_HOME" "$CODEX_HOME"
cd "$SRC" && run bash ./install.sh --cmd agmsg < /dev/null
echo "--- HOME agaci (kurulum sonrasi):"; (cd "$HOME" && find . -maxdepth 4 -not -path "./tools/*" | sort | head -50)
SK="$AGMSG_INSTALL_HOME/.agents/skills/agmsg"; ls "$SK" 2>&1 | head

step "3. iki sahte ajan: a1, a2 (takim t1)"
mkdir -p "$HOME/proj-a1" "$HOME/proj-a2"
run bash "$SK/scripts/join.sh" t1 a1 codex "$HOME/proj-a1"
run bash "$SK/scripts/join.sh" t1 a2 codex "$HOME/proj-a2"
run bash "$SK/scripts/team-list.sh" 2>&1 | head -20

step "4. gonder a1 -> a2, al a2"
run bash "$SK/scripts/send.sh" t1 a1 a2 "merhaba a2, ben a1 (uctan uca deneme)"
echo "--- a2 gelen kutusu:"; run bash "$SK/scripts/inbox.sh" t1 a2
echo "--- a2 ikinci okuma (okundu isaretli olmali):"; run bash "$SK/scripts/inbox.sh" t1 a2

step "5. yanit a2 -> a1, al a1"
run bash "$SK/scripts/send.sh" t1 a2 a1 "yanit a1, mesaj alindi"
run bash "$SK/scripts/inbox.sh" t1 a1

step "6. olumsuz: kayitsiz gonderen / alici (reddedilmeli)"
run bash "$SK/scripts/send.sh" t1 a1 yok "kimse yok"
run bash "$SK/scripts/send.sh" t1 sahte a2 "taklit?"

step "7. kimden taklidi: a1 ismiyle baska aci? (gonderen dogrulamasi var mi)"
echo "send.sh dogrudan 'from' argumani alir; kimlik dogrulamasi yok mu bak:"
run bash "$SK/scripts/send.sh" t1 a2 a1 "ben a2 degilim ama a2 diyorum"
echo "--- history:"; run bash "$SK/scripts/history.sh" t1 a1 10

step "8. db"
sqlite3 -header -column "$AGMSG_HOME/agmsg/db/messages.db" ".schema messages" "select * from messages;" 2>&1 | cut -c1-200 | head -30
find "$AGMSG_HOME" "$AGMSG_INSTALL_HOME" -name "messages.db" | head
step "BITTI"
