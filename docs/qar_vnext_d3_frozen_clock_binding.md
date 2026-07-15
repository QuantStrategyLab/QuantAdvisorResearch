# QAR D3 frozen-clock evidence binding

This isolated representative-fixture slice uses two independent daily producer calls under an explicit harness-frozen `generated_at`. The exact frozen value is checked against both report snapshots, both manifest source records, build evidence, and downloaded verification evidence. The artifact remains exactly `report.json`, `report.html`, and `manifest.json`; no production trust, Pages, publisher, weekly/monthly, legacy, or identity integration is added.
