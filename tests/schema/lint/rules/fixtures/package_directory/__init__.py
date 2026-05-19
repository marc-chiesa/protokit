"""D6c U3 R8 + R8b parity-fixture corpus.

Mirror of :mod:`tests.schema.lint.rules.fixtures.package_same` for the
cross-file directory/package rule family. The ``_buf_smoke/`` subtree
contains 10 buf v1.69.0 recorded NDJSON snapshots that
:mod:`tests.parity.test_parity_package_directory` consumes to verify
protokit's R8 + R8b emit matches buf's byte-for-byte.

Fixtures (per KTD-10 + Finding #3 addition):

- 5 base: ``matched-dir``, ``mismatched-dir``, ``split-package-multi-dir``,
  ``single-file-dir``, ``proto-root-mixed``.
- 1 OQ-4 sub-question: ``no-package-mixed`` (multi-declared + packageless
  — empty-mixed-multi arm).
- 3 edge-case discriminators: ``n3-directories-split`` (R8 with 3 dirs),
  ``n3-packages-same-dir`` (R8b with 3 packages), ``cofire-r8-r8b``
  (both rules on the same file).
- 1 ce:review Finding #3 follow-up: ``single-declared-no-package``
  (1-declared + 2-packageless — empty-mixed-single arm).
"""
