# Shuttle download integration

The current backend and CLI register `upgrade inspect` and `upgrade download`. Builds are local only; no release or installer was published.

Use the newly built CLI with the newly built `frame_backend.dll` discoverable beside it or in process PATH. `build/native/Release/frame_backend.dll` is the verified backend. Offline example:

```powershell
$env:PATH = "D:\OneDrive\LWX\FRAME\build\native\Release;" + $env:PATH
& "D:\OneDrive\LWX\FRAME\frontend\Frame.Cli\bin\Release\net10.0-windows\win-x64\frame.exe" upgrade inspect --path "D:\project\demoB\build-phase2-final\demoB.bin" --json
```

`upgrade download` uses the existing transport session, E8 encoder, packet matching, cancellation and progress. Select `--wire e8`, verified device address (current Shuttle constant is 1), and an adequate `--timeout`; `--force true` bypasses version comparison only, never target/storage policy. E9 download is explicitly rejected because this Shuttle endpoint currently implements E8. Stop acquisition and wait for probe writes before download. No physical download was performed in this work.

Wire schema is unchanged from base bootloader protocol: set 01 INFO08/READY09/DATA0A/END0B, same-command ACKs, DATA1033 with 1024-byte FF-padded payload and CRC16, file CRC16 at END. SHUT CRC/header checks happen before host transmission and on-device commit. No invented footer, backup partition, alternate command words or reset-to-boot step are added. The endpoint binds source address/dynamic source for a session and expires idle sessions after 30 seconds.

The return `committed=true` means a successful device commit ACK; `running="not confirmed"` does not assert application initialization or board timing. E8 has no sequence or offset in its one-byte DATA ACK; final full-image validation is authoritative and failures are reported, not treated as success.

Validation: existing CTest 6/6, actual CLI offline inspection, and `D:/project/Shuttle/tests/integration/frame_loopback.py`. The latter connects only to 127.0.0.1 and uses real `update.c` with an in-memory storage adapter, including lost DATA/END ACKs. Hardware tests remain pending. The loopback drops ACKs; it does not prove arbitrary delayed/reordered ACK association. E8 has no per-DATA-ACK identity, so a late old ACK may match a later DATA wait despite clearing already queued ACKs. Final full-image validation/commit remains the integrity gate; transfer may fail and require retry. Physical port/protocol latency behavior is still untested.
