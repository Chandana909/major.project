# The huge ledger, compressed

`huge_seed_606.tar.xz` holds the 500,000-invoice ledger `huge_seed_606` (15,000 vendors; RESULTS.md, Section 5.1):
its nine files, about 330 MB of CSV, compressed with xz to 52,120,116 bytes, so that it fits in the repository
without Git LFS (GitHub refuses files above 100 MiB, and `invoices.csv` alone is 127 MB).

| File | Bytes |
|---|---|
| `invoices.csv` | 127,436,837 |
| `purchase_orders.csv` | 75,024,772 |
| `goods_receipts.csv` | 66,763,686 |
| `approval_logs.csv` | 45,509,591 |
| `labels.csv` | 12,413,425 |
| `vendor_master.csv` | 1,860,163 |
| `eval_subset.csv` | 333,584 |
| `README.md`, `manifest.json` | the dataset's own description and hashes |

SHA-256 of the archive: `2b0075549fd85d3c16f02a6f6a5ef1a034b4e9dcdc8dd0cfc621e0b26259e267`. Every CSV in it matches
the SHA-256 committed in `results/huge_seed_606/manifest.json` (checked when the archive was made, 21 November 2026).

**Using it instead of regenerating it.** Generating the ledger from its seed takes hours; extracting it takes a minute.
From `auditiq/`:

    python -c "import tarfile; tarfile.open('data_archives/huge_seed_606.tar.xz').extractall('data_huge', filter='data')"
    python -m evaluation.huge

`evaluation.huge` finds the ledger in its work folder (`data_huge/huge_seed_606/`, not committed), checks every file
against the committed hashes instead of generating it, and runs its steps. With `--work <folder>`, extract into that
folder instead.
