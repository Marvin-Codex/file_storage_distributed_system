# LANVault M9 demo

Run each command from the repository root in a separate terminal. On Windows,
set environment variables with `$env:NAME="value"`.

## 1. Start the master

```powershell
$env:ROLE="master"
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 8000
```

Create a staff user and a `Computing` group through `/admin/`, then add the
user to that group.

## 2. Start three nodes and heartbeats

Start three node servers on ports 9001, 9002, and 9003 with matching
`NODE_NAME`, `NODE_ADDRESS`, and `NODE_DATA_DIR` values. For example:

```powershell
$env:ROLE="node"; $env:NODE_NAME="node1"; $env:NODE_ADDRESS="http://127.0.0.1:9001"; $env:NODE_DATA_DIR=".\data\node1"; $env:MASTER_URL="http://127.0.0.1:8000"; .\.venv\Scripts\python.exe manage.py runserver 9001
```

Run one `run_heartbeat` command per node using the same variables.

## 3. Upload and fail over

Upload `/Computing/notes.pdf` through the API. Open
`http://127.0.0.1:8000/dashboard/` and confirm two healthy replicas.

Stop one node that holds a replica. Download the file; the master should serve
it from the remaining healthy replica.

## 4. Detect and repair

After the dead-node threshold has elapsed, run:

```powershell
$env:ROLE="master"
.\.venv\Scripts\python.exe manage.py monitor --once
```

The dashboard should show a replacement replica on the third node.
