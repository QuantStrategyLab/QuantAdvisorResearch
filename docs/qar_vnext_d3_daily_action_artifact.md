# QAR vNext D3 daily action artifact

This workflow is an isolated, repository-representative fixture acceptance slice:

1. `build_advisory_report(..., cadence="daily")` reads the fixed examples CSVs.
2. Existing `qar.preview_bundle.v1` writes exactly `report.json`, `report.html`, and `manifest.json` under a unique `$RUNNER_TEMP` destination.
3. The bundle is read back before `actions/upload-artifact@v7`.
4. The uploaded artifact is downloaded to a separate temporary directory and read back again.

Evidence explicitly identifies `source_kind=repository_representative_fixture`; it is not live producer or production-trusted evidence. The workflow does not modify weekly/monthly workflows, publisher, archive/feed, Pages, identity, or persistence. Issue #50 remains the production-trust hardening gate.
