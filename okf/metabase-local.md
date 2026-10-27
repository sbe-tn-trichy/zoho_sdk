---
type: operations
description: Local Metabase Docker installation and SQLite mount paths on macOS.
---

# Local Metabase

Metabase runs in the existing Colima Docker VM on this Mac. Its UI is bound only
to `127.0.0.1:3001`; port 3000 belongs to the existing token service.

- Container: `metabase`, image `metabase/metabase:latest` as pulled during installation.
- Persistent application settings: Docker volume `metabase_data`, mounted at `/metabase-data`.
- Application database: embedded H2 at `/metabase-data/metabase.db` (local single-user setup).
- Memory limit: 1536 MB; Java maximum heap: 1 GB.
- Docker local log rotation: 10 MB per file, two files.
- Timezone: Asia/Kolkata.

There is no separate application database container and no copied SQLite dataset.
Existing host directories are mounted read-only:

| Host output directory | Container directory | SQLite connection file |
|---|---|---|
| `output/customer_cleanup` | `/data/customers` | `/data/customers/customers.sqlite3` |
| `output/books_custom_modules` | `/data/modules` | `/data/modules/modules.sqlite3` |

Open <http://localhost:3001> and complete the initial administrator setup, then
add SQLite connections using those container paths. Customer constants are combined
with customer rows by the `customers_full` view. The application settings volume is
independent from the source SQLite files; preserve it when replacing the container.
Metabase's H2 database is distinct from the SQLite databases being analyzed.

```sh
colima start
docker start metabase
curl http://127.0.0.1:3001/api/health
```

Stop just the app with `docker stop metabase`; stop the VM with `colima stop`.
The container uses `--restart unless-stopped` when Docker is running; Colima was not
configured as a macOS login service. Avoid pulling duplicate versions or adding database
containers for this local setup. Docker images/runtime files and the VM consume disk;
`docker system df` and `du -sh ~/.colima` report their respective usage without assuming
the virtual disk's maximum capacity is allocated space.

References: [Docker installation](https://www.metabase.com/docs/latest/installation-and-operation/running-metabase-on-docker),
[SQLite connections](https://www.metabase.com/docs/latest/databases/connections/sqlite).
