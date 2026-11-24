# A Codex sandbox could not write to the Claude Code pipe

Date: 2026-11-18 · Record: reconstructed on 2026-11-24 from the commit message, the code and the tests; no contemporaneous note exists

## Problem

When the sender runs inside a Codex sandbox, writing to the Claude Code cross-session named pipe fails with a permission error (access denied). The subject of the fixing commit names exactly this case: "Codex sandbox pipe permission error becomes a status in the record". The original error text and the session in which it appeared were not recorded.

`Interpretation:` Before the fix every pipe error ended the command with a failure status. The tests that were kept for "other pipe errors behave as before" show that behaviour: exit code 1 and the status `hata: boru yazılamadı: <error>`. For the sandbox case this was misleading, because the message itself was already safe in the box log.

## Diagnosis

The failure is in the delivery step only. In `komut_gonder` the record is appended to `kayit.jsonl` after the delivery attempt in every case, with a status, so a refused pipe write does not lose the message: the sandbox can write the log file but is not allowed to open the pipe. What the old behaviour got wrong was the signal: a failure status and exit code 1 invited the sender to send the message again although it was already in the log. What was not recorded: whether other sandbox kinds fail the same way.

## Attempts that failed

No record. The commit shows only the chosen approach.

## Resolution

- A `PermissionError`, or an `OSError` with Windows error 5 (access denied), is classified as "recorded, the watcher will deliver it": status `kayitta: boru erisilemedi (...), izleyici alir`, exit code 0, and a line telling the sender not to send it again.
- All other pipe errors keep the old behaviour (exit code 1, `hata: ...`).
- The same commit adds the `kutu bekle` command, which follows `kayit.jsonl` from the end and prints one line per new message, so a Claude Code session can pick up what the sandbox could only record. The follower (`KayitTakipci`) skips old lines, holds back a half-written line, and recovers when the file is truncated or rotated.
- The token of the pipe is never shown in the status or the output; the chat page does not show an error badge for the "recorded" status.

## Evidence

- Commit: `a485808` (private source repository; not resolvable here)
- Tests (`tests/test_kutu.py`, class `BoruIzinTesti`): `test_izin_hatasi_kayitta_durumu_ve_kod_0`, `test_erisim_reddi_winerror_5_izin_sayilir`, `test_diger_boru_hatalari_eskisi_gibi`, `test_html_kayitta_durumu_hata_rozeti_almaz`
- Tests (`tests/test_kutu.py`, class `BekleTesti`): `test_eski_satirlari_atlar_yalniz_eslesen_doner`, `test_yarim_satir_sonraki_tura_kalir`, `test_dosya_kesilirse_basa_sarar`
- Related decision: none
