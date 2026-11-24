---
status: "accepted"
date: 2026-11-18
decision-makers: the repository maintainer
consulted: AI coding agents (Claude Code) wrote the implementation; whether an agent proposed the option is not recorded
informed: none
---

# Sign messages with a per-agent HMAC-SHA256 key instead of trusting the `kimden` label

Record: reconstructed on 2026-11-24 from the code, the tests and the end-to-end notes. The deliberation at the time was not recorded, so the options below are the ones the repository's documents and code let a reader reconstruct, not a log of what was weighed.

## Context and Problem Statement

Every message in the box carries a `kimden` (sender) field that is only a label: any process that can append a line can write any name. Text from another agent is fed to a model, so a forged sender name is a prompt-injection path ("this message comes from the trusted advisor, do what it says"). How can the box tell a message that really passed through the bridge under a given name from a line that was typed in or edited by hand?

## Decision Drivers

* The label must be bound to something a forger without the key cannot produce.
* Python standard library only (see [0002](0002-python-standard-library-only.md)).
* Existing unsigned boxes must keep working (backward compatibility).
* Honest limits: the keys live on the same machine as the box.

## Considered Options

* Keep the `kimden` label only (status quo before signing).
* A per-agent secret key and an HMAC-SHA256 over the immutable fields of each record.
* Asymmetric signatures (a key pair per agent).
* Rely on the transport (the operating-system pipe or the queue command) instead of signing.

## Decision Outcome

Chosen option: "a per-agent secret key and an HMAC-SHA256 over the immutable fields", because it is the only option that binds the sender name to a secret using the Python standard library alone, and it catches the failures the box actually has to defend against (label forgery, hand-edited or tampered lines).

The signed fields are `id`, `ts`, `kimden`, `kime`, `konu` and `metin`; `durum` is not signed because it changes after delivery. A key is 32 random bytes (from `secrets.token_hex`) in one file per agent name; names are limited to lower-case letters, digits, `-` and `_`, at most 32 characters, which rejects path escapes. A message is signed when the sender has a key; a box can require signatures (`--imza-zorunlu`). A wrong signature is always rejected, even when signatures are not required.

### Consequences

* Good, because a forged `kimden`, an edited message and a signature made with the wrong key are all rejected (tests below).
* Good, because unsigned boxes keep working: by default an unsigned message is accepted with an `[imza: yok]` label.
* Bad, because the keys sit in the same user account as the box: a process that can read the key folder can sign as any agent. The README states this limit.
* Bad, because a re-inserted copy of an identical signed line is not detected (there is no duplicate-`id` check). The README states this too.
* Bad, because "signature valid" only means "this message went through this bridge with that name's key"; for adapter replies the bridge signs on behalf of the tool, so it does not mean the tool itself vouched for the answer.

### Confirmation

Tests in `tests/test_imza.py`: `test_degistirilen_icerik_reddedilir` (edited content), `test_taklit_kimden_etiketi_reddedilir` (forged label), `test_imzasiz_ve_anahtarsiz` (unsigned and keyless), `test_zorunlu_olmayan_kipte_imzasiz_gecer_yanlis_imza_gecmez` (unsigned passes, a wrong signature never passes when signatures are optional), `test_zorunlu_kipte_yalniz_gecerli_iletilir` (required mode). The end-to-end script `uctan-uca.py` checks the same cases against the real tools; its summary is in [OKU.tr.md](../../OKU.tr.md) section 4.

## Pros and Cons of the Options

### Keep the `kimden` label only

* Good, because there is nothing to manage.
* Bad, because any writer can claim any sender; the end-to-end notes record that even the agmsg project, from which the pipe format was learned, does not verify the sender ([OKU.tr.md](../../OKU.tr.md) section 3).

### A per-agent secret key and an HMAC-SHA256 over the immutable fields

* Good, because `hmac` and `hashlib` are in the standard library and the comparison uses `hmac.compare_digest`.
* Good, because the check is local and offline.
* Bad, because a shared-secret scheme cannot separate the signer from the verifier: whoever can verify a name can also sign as it.

### Asymmetric signatures

* Good, because verifying would not need the signing key.
* Bad, because the Python standard library has no public-key signature primitive, so this would add a third-party dependency (against [0002](0002-python-standard-library-only.md)).
* `Interpretation:` With the keys in the same user account, asymmetric signatures would not remove the main limit stated above either.

### Rely on the transport

* Bad, because the two delivery paths are Codex's official queue command and Claude Code's cross-session pipe, and the log is a plain file that anyone with write access can append to. `Interpretation:` neither path gives the receiving model a verified sender name.

## More Information

* Commit `68d67ea` of the private source repository introduced signing together with the adapters; the code is `kutu_imza.py`.
* Related: [0003](0003-untrusted-by-default-trusted-sender-list.md) builds on a valid signature.
* The setup commands and the known limits are in `README.tr.md` ("Kimlik: HMAC imzası").
