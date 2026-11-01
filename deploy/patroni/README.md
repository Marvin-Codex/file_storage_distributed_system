# LANVault controller failover

The failover topology is:

```text
controller-1 ─┐
controller-2 ─┼─ ... controller-N
controller-N ─┘       │
       Patroni + PostgreSQL + LANVault (ROLE=controller)
                      │
                 lanvault.local
```

Each controller runs both the Django control plane and a local storage-node
service. Patroni uses the matching etcd cluster for quorum and promotes the
most up-to-date healthy PostgreSQL member. The Django process runs on every
controller, but `/ready/` returns `200` only on the PostgreSQL primary.

1. Choose an odd number of controller machines. Three is the recommended
   minimum; five or seven provide additional failure tolerance.
2. Install PostgreSQL, etcd, Patroni, and the project requirements on every
   controller.
3. Copy `patroni.yml.example` to each machine and change `name`,
   `connect_address`, and the node-specific PostgreSQL data directory.
4. Use the same `scope`, database credentials, and Django `SECRET_KEY`/
   `CLUSTER_SECRET` on every controller.
5. Point `DATABASE_URL` at the local PostgreSQL instance and set
   `HA_ENABLED=True`.
6. Run migrations once against the Patroni primary.
7. Run Django and the monitor on every controller.
8. Configure the `lanvault.local` DNS health automation to use
   `http://<controller>:8000/ready/`. Only the controller returning `200`
   should be published as the application A record.

Do not publish every controller in round-robin DNS without health checks:
standby Django processes intentionally return `503` from `/ready/` and are
not safe to receive writes. Patroni handles database election; DNS health
automation handles application traffic routing.

For five or seven controllers, replace the example `etcd3.hosts` list with
all etcd members and use the same complete membership list on every
controller. Patroni's quorum is a majority: three of five, four of seven,
and so on. Keep the controller count odd so a network partition can be
resolved without a tie.

The example contains placeholders for passwords and private LAN addresses.
Replace them before use and never commit real credentials.
