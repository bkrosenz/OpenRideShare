# OpenRideShare

Invitation-only community ride sharing. The Android client and backend application are Python; Kubernetes and Android build configuration are declarative manifests.

## Current Scope

- FastAPI backend, SQLAlchemy persistence, PostgreSQL for deployment, and SQLite for local development.
- Username/password accounts require a single-use, expiring invitation. Passwords are bcrypt-hashed and API sessions use short-lived HS256 bearer tokens.
- Driver dispatch calculates OSM/OSRM driving routes to available drivers, sorts them by approach distance, then atomically claims the closest available driver. Idempotency keys prevent duplicate ride creation on client retries.
- Fare is `max($0.76 x route miles, configured local hourly wage x route hours + allocated monthly pod cost)`. Pod count is `ceil(active users / USERS_PER_POD)`, with a one-pod minimum. The projected pod cost is divided across projected monthly rides. The fare breakdown is returned with each request; tips are separate.
- Venmo is an explicit app handoff using the configured Venmo username. OpenRideShare does not collect card or bank credentials and does not confirm settlement.
- Uber/Lyft handoff links are returned only after no community driver is available and the rider opted in. The Android client checks whether a link can be opened before launching it.
- The Python/Kivy Android client supports account creation, login, ride requests, tipping, driver availability, and polling assigned requests.
- The mock simulation runs multiple riders against a finite driver pool and checks fare floors and unique driver assignments.

## Local Backend

Requirements: Python 3.11+ and `uv` (or an equivalent environment/package installer).

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e '.[test]'
export JWT_SECRET="replace-with-a-random-secret-at-least-32-characters"
export INVITATION_ADMIN_KEY="replace-with-a-long-random-admin-key"
export DATABASE_URL="sqlite:///./openrideshare.db"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn backend.app.main:app --reload
```

Issue an invitation with `POST /admin/invitations` and the `X-Admin-Key` header, then register at `/auth/register`. The invitation is returned once and only its hash is stored. API docs are available at `/docs` during development.

Run checks with `.venv/bin/python -m pytest -q`.

## Android Client

Install the Android optional dependencies and Buildozer/Android SDK tooling, then run `buildozer android debug` from the repository root. The app asks for an HTTPS API endpoint; set it to the deployed API host. Use a real HTTPS endpoint for emulator/device testing. The client keeps its access token in memory only, so users sign in again after restarting the app.

## Simulation

The simulation has its own dependency list and can use its own environment:

```sh
uv venv simulation/.venv
uv pip install --python simulation/.venv/bin/python -r simulation/requirements.txt
PYTHONPATH=. simulation/.venv/bin/python simulation/run_simulation.py
```

It creates mock rider and driver records in an isolated in-memory SQLite database, uses mock OSM/traffic adapters, and checks that each available driver is assigned at most once.

## Kubernetes / EKS

Build and publish the API image, provision PostgreSQL (for example encrypted RDS with TLS required), an ingress controller, and a TLS certificate. Create the `openrideshare-secrets` secret through a secrets manager/External Secrets integration; required keys are `database-url`, `jwt-secret` (32+ random characters), and `invitation-admin-key`. Optional keys are `waze-feed-token` and `venmo-username`. Never commit secret values.

Set the image in `k8s/app.yaml` and `k8s/migration-job.yaml`, replace the example ingress host, and configure the TLS secret. Apply `k8s/app.yaml` once to create the namespace/configuration, then run the migration job and wait for it to complete before applying the deployment again:

```sh
kubectl apply -f k8s/app.yaml
kubectl apply -f k8s/migration-job.yaml
kubectl -n openrideshare wait --for=condition=complete job/openrideshare-migrate --timeout=180s
kubectl apply -f k8s/app.yaml
```

The Deployment runs non-root with a read-only root filesystem; the HPA scales from 2 to 30 replicas at 65% average CPU. Install metrics-server and tune resource requests, limits, and HPA targets for measured load. The manifests are a workload baseline, not a complete EKS account/network/database provisioning stack.

## Provider And Cost Configuration

- `OSRM_URL` must point to a production-capable OSRM service using OpenStreetMap data. The public OSRM demo URL is only a development default and has no availability/SLA guarantee.
- Live Waze data requires an authorized Waze for Cities feed configured through `WAZE_FEED_URL` and `WAZE_FEED_TOKEN`. The app does not scrape Waze or claim access to a public consumer API. Without a feed, routes use OSM road data and the base route ETA only.
- Set `LOCAL_WAGE_CENTS_PER_HOUR` to the applicable wage for the initial service area. The current implementation has one configured wage, not a multi-jurisdiction wage resolver.
- `POD_MONTHLY_COST_CENTS` and `USERS_PER_POD` are operator estimates, not live AWS billing data. The fare estimate uses projected monthly rides (`active users x RIDES_PER_USER_MONTH`) and the configured pod count. Calibrate these values against actual EKS/EC2/networking costs before charging riders.
- Replace the public OSRM default, example domain, and all sample cost values before production.

## Security And Production Readiness

The implementation minimizes stored payment information, hashes passwords and invitation codes, validates coordinates and amounts, sets no-store/security headers, uses atomic conditional driver claims, and references runtime secrets from Kubernetes. Production still requires managed TLS, encrypted database/storage and backups, least-privilege secret management, network policy, centralized abuse/rate limiting, monitoring, incident response, and a security/privacy review. Venmo handoff is not payment settlement or escrow; verify payment through a supported merchant workflow before relying on it for ride completion. The current prototype has no account recovery, push notifications, or driver decline/offer-expiry workflow.
