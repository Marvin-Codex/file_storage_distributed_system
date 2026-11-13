import pypandoc

content = r"""# Development Workflow: Distributed File Storage System

## 1. Project objective

Develop a reliable, scalable Django-based Distributed File Storage System supporting two planned operating modes:

1. **Master Mode:** One designated master coordinates the cluster, manages metadata, schedules storage operations and coordinates replication. Other nodes provide storage services.
2. **Decentralized HA Mode (future):** Every node acts as a controller and storage node. There is no permanently designated master.

### Immediate development priority

Complete and stabilize Master Mode first.

Use SQLite for the current development and testing environment. Keep the database architecture portable so PostgreSQL can be introduced later.

---

## 2. Development rules

Follow these rules throughout development:

- Inspect the existing project before changing anything.
- Preserve working code and existing functionality.
- Do not rewrite the project from scratch.
- Do not introduce unnecessary Django apps, dependencies or architectural abstractions.
- Work incrementally, one phase at a time.
- Follow Django conventions and maintain clear separation of responsibilities.
- Use services for reusable business logic.
- Use controllers or service modules for cluster coordination where appropriate.
- Keep node communication authenticated.
- Never expose storage directories or sensitive credentials.
- Handle network failures, unavailable nodes and interrupted transfers gracefully.
- Write tests for every important feature.
- Do not claim a feature works without testing it.
- Do not proceed to the next phase until the current phase passes its acceptance tests.

Before modifying files, explain the proposed changes and identify possible compatibility issues.

---

# PHASE 1: EXISTING PROJECT AUDIT

Inspect the complete project structure.

Examine:

- Django settings and environment configuration.
- Installed applications.
- Database models and migrations.
- Master and storage-node roles.
- Node registration and heartbeat mechanisms.
- Node communication APIs.
- File upload and download implementations.
- Physical storage implementation.
- File metadata management.
- Replication implementation.
- Authentication and authorization.
- Existing tests.
- Management commands.
- Error handling and logging.

Pay particular attention to:

- `vault/services/node_client.py`
- `node/views.py`
- `node/storage.py`
- `node/management/commands/run_heartbeat.py`
- `config/settings.py`

Identify incomplete implementations, duplicated logic, security weaknesses and existing errors.

**Deliverable:** An architecture audit report showing what works, what is incomplete, what needs fixing and the recommended implementation order.

Do not make major architectural changes during the audit.

# PHASE 2: STABILIZE MASTER MODE

Make the existing master architecture reliable.

The master must:

- Accept client requests.
- Authenticate users.
- Manage file metadata.
- Maintain the registered-node inventory.
- Monitor node availability.
- Select suitable storage nodes.
- Coordinate uploads, downloads and deletions.
- Coordinate file replication.
- Maintain replica-location information.

Storage nodes must:

- Accept authenticated storage requests.
- Store file data locally.
- Retrieve stored files.
- Delete stored files when authorized.
- Report health and available capacity.
- Send heartbeat information to the master.

Ensure that master and storage-node responsibilities are clearly separated.

**Acceptance criteria:**

- Master starts successfully.
- Storage nodes connect successfully.
- Authentication works.
- Heartbeats update node status.
- The master can identify unavailable nodes.
- Existing functionality remains operational.

# PHASE 3: RELIABLE FILE OPERATIONS

Implement and test the complete file lifecycle.

### Upload

1. Client uploads a file to the master.
2. Master validates the request.
3. Master generates a unique file identifier.
4. Master selects storage nodes.
5. File data is transferred to the selected nodes.
6. Nodes confirm successful storage.
7. Master records file metadata and replica locations.
8. Client receives a successful response.

### Download

1. Client requests a file.
2. Master retrieves its metadata.
3. Master identifies available replicas.
4. Master selects a healthy replica.
5. File is retrieved and returned to the client.

### Delete

1. Client requests deletion.
2. Master verifies authorization.
3. Master identifies all known replicas.
4. Master coordinates deletion.
5. Master updates metadata after confirming the applicable deletion results.

### Reliability requirements

- Support files larger than Django's default request-memory threshold.
- Avoid loading unnecessarily large files entirely into memory.
- Use configurable connection and transfer timeouts.
- Verify file integrity using SHA-256.
- Handle interrupted transfers.
- Avoid recording a file as successfully replicated before confirming storage.
- Prevent duplicate or conflicting operations where possible.
- Maintain clear operation logs.

Investigate the existing large-file upload timeout before changing configuration. Use server logs and controlled upload tests to establish the actual cause.

**Acceptance criteria:**

Test small, medium and large files.

Verify uploaded content against downloaded content using SHA-256.

# PHASE 4: REPLICATION AND STORAGE MANAGEMENT

Implement reliable replica management.

Requirements:

- Configurable replication factor.
- Replicas distributed across different nodes.
- Node capacity awareness.
- Node health awareness.
- Detection of missing replicas.
- Detection of failed storage operations.
- Automatic replica repair.
- Protection against unnecessary duplicate replicas.
- Accurate replica-location tracking.

For initial development, use a simple, understandable placement algorithm.

Do not introduce complicated distributed consensus mechanisms in Master Mode.

**Acceptance criteria:**

- Files are stored on the configured number of healthy nodes where capacity permits.
- Failed nodes do not receive new storage assignments.
- Missing replicas can be restored.
- Replica metadata matches actual stored data.

# PHASE 5: AUTOMATIC NODE ONBOARDING

Implement automatic onboarding for Master Mode.

A new storage node should be able to join without manually editing database records.

Proposed workflow:

1. Administrator generates a secure, expiring enrollment token.
2. New node starts with the master address and enrollment token.
3. New node contacts the master.
4. Master validates the token.
5. Master registers the node.
6. Master issues node-specific credentials.
7. New node begins sending heartbeats.
8. Master verifies node health.
9. Node becomes eligible for storage allocation.

Example command:

```bash
python manage.py join_cluster --master http://MASTER-IP:8000 --token TOKEN --name NODE-B
```

Security requirements:

- Expiring, single-use enrollment tokens.
- Node-specific credentials.
- Authentication on all storage APIs.
- Credential revocation.
- Secure communication support through HTTPS.
- Never expose enrollment tokens in logs.

Keep the onboarding design adaptable to future decentralized peer discovery.

# PHASE 6: FAILURE HANDLING AND RECOVERY

Implement practical Master Mode failure handling.

Handle:

- Storage node going offline.
- Storage node restarting.
- Network interruptions.
- Failed uploads.
- Failed downloads.
- Failed deletions.
- Insufficient storage capacity.
- Corrupted replicas.
- Interrupted replication.

When a node reconnects:

1. Verify its identity.
2. Check its health.
3. Reconcile its stored-file inventory with master metadata.
4. Identify missing or inconsistent replicas.
5. Resume necessary recovery operations.

Do not delete files simply because a node temporarily becomes unreachable.

Document the limitations of Master Mode when the master itself becomes unavailable. Do not claim master failover is implemented unless it actually is.

# PHASE 7: DATABASE PORTABILITY

Continue using SQLite for current development.

Requirements:

- Avoid SQLite-specific application logic where practical.
- Use Django ORM for database operations.
- Avoid unnecessary raw SQL.
- Use proper migrations.
- Handle transactions appropriately.
- Keep database configuration environment-based.
- Document any SQLite-specific limitations.

Prepare and test a PostgreSQL configuration.

Do not attempt to synchronize independent SQLite databases across nodes.

Do not introduce a shared SQLite database over a network filesystem.

PostgreSQL migration is a future milestone, not a reason to interrupt current Master Mode development.

# PHASE 8: SECURITY AND PERFORMANCE

Review:

- User authentication.
- Node authentication.
- Permissions.
- Upload validation.
- File integrity.
- Path traversal protection.
- Request size limits.
- Secure secret management.
- API rate limiting.
- Network timeouts.
- Resource usage.
- Logging and audit trails.

Use streaming for large file transfers where appropriate.

Never expose internal storage paths or node credentials to ordinary users.

Keep DEBUG disabled in production.

# PHASE 9: AUTOMATED TESTING

Build automated tests for:

1. Master initialization.
2. Node registration.
3. Node authentication.
4. Heartbeat monitoring.
5. File uploads.
6. File downloads.
7. File deletion.
8. Replication.
9. Replica repair.
10. Node failure.
11. Node recovery.
12. Interrupted transfers.
13. Invalid enrollment tokens.
14. Unauthorized API requests.
15. Large-file integrity.

Test using multiple local node processes or separate machines where possible.

Do not rely exclusively on mocked node responses.

# PHASE 10: FUTURE DECENTRALIZED HA PREPARATION

Do not implement full decentralized HA yet.

Instead, document how the existing system can eventually evolve into a decentralized architecture.

Future requirements:

- Every node runs controller and storage services.
- Every node can accept client requests.
- Peer discovery.
- Secure peer enrollment.
- Distributed membership.
- Temporary leader election where required.
- Consensus-backed cluster metadata.
- Replica placement across peers.
- Automatic recovery.
- PostgreSQL-backed coordination where appropriate.

Avoid permanently embedding the assumption that only one machine can perform cluster-management responsibilities.

However, do not sacrifice the reliability of the current Master Mode just to prepare for future HA.

---

# FINAL DEVELOPMENT INSTRUCTIONS

Work in this exact order:

1. Audit the existing project.
2. Stabilize Master Mode.
3. Fix file operations.
4. Implement reliable replication.
5. Implement automatic node onboarding.
6. Implement failure handling.
7. Improve database portability.
8. Complete security and performance improvements.
9. Complete automated testing.
10. Document the future decentralized HA architecture.

After every phase:

- List files inspected.
- List files created or modified.
- Explain important changes.
- Run relevant migrations.
- Run tests.
- Report actual test results.
- Identify remaining issues.
- Wait for approval before moving to the next phase.

**Do not implement all phases in one uncontrolled operation.**

The final objective is a reliable, secure, maintainable distributed storage system that works today in Master Mode and can evolve into decentralized HA without requiring a complete rewrite.
"""

output_path = "/mnt/data/distributed_storage_development_workflow.md"
pypandoc.convert_text(
    content,
    "md",
    format="md",
    outputfile=output_path,
    extra_args=["--standalone"]
)
print(output_path)
