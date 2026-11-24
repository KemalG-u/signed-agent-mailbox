# The default `--claude-ad` can point at the wrong Claude Code session

Date: 2026-11-18 · Record: reconstructed on 2026-11-24 from the commit message, the README and the tests; whether the trap caused a wrong delivery in practice was not recorded

## Problem

`gonder --kime claude` writes into the pipe of the Claude Code registration named by `--claude-ad`. Without that option the name `danisman` is used. Each `claude-kaydet --ad <name>` leaves one registration file, and a file is not removed when its session ends. So the default registration can belong to another, older or already closed session, and the message then reaches the wrong session or fails with a pipe error. The README documents this as "Tuzak" ("trap").

## Diagnosis

The default name is a convention, not a check: nothing tells the sender that several registrations exist. The root cause is a stale-registration problem, not a bug in the delivery code.

## Attempts that failed

No record of a rejected design. The commit message states the constraint that shaped the fix: the default behaviour must not change.

## Resolution

- When `--kime claude` is used without `--claude-ad` and more than one registration exists, `gonder` prints a warning on the error stream. The warning lists the registered names (never the token) and shows the explicit form `--claude-ad <name>`.
- The send itself proceeds with the default name exactly as before, so existing scripts keep working.
- The README explains the trap and tells each session to register under its own name and to name the target explicitly. `kutu durum` lists the registered names.

## Evidence

- Commit: `93ed580` (private source repository; not resolvable here)
- Tests (`tests/test_kutu.py`, class `ClaudeAdUyariTesti`): `test_ad_verilmedi_ve_birden_cok_kayit_uyarir` (warning, names listed, token absent), `test_varsayilan_davranis_korunur_danisman_kaydina_yazar` (default unchanged), `test_acik_ad_uyari_vermez_ve_o_kayda_yazar` (explicit name, no warning), `test_tek_kayit_uyari_vermez` (one registration, no warning)
- Documentation: `README.tr.md`, section "Tuzak: `--claude-ad` hedef oturumu seçer"
- Related decision: none
