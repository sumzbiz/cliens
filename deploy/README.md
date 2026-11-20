# Deploying

Everything is Terraform and one shell script. Nothing is created by hand in the
AWS console, and there is no SSH key to manage — the instance is reached through
SSM Session Manager.

## What gets created

| | |
| --- | --- |
| EC2 `t4g.small` | Runs the whole stack in Docker Compose: Postgres/PostGIS, the API, and Caddy |
| Elastic IP | A stable address, so a stop/start does not change the URL |
| S3 bucket | Private. Deploy artifacts only; the instance pulls from it using its IAM role |
| SSM parameters | The database password and API keys, as `SecureString` |
| IAM role | SSM access, read on that one bucket, read on those parameters — nothing else |

No NAT gateway, no load balancer, no RDS. Those are the right answer at scale
and the wrong answer here: a NAT gateway alone costs more per month than this
entire stack, and this app makes heavy outbound calls (every map tile is fetched
and recomposited server-side) so it would be metered on top.

## First deploy

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
# fill in postgres_password, and the Sarvam keys if you want the Tamil voice

terraform -chdir=infra init
terraform -chdir=infra apply

bash deploy/deploy.sh
```

`apply` takes about two minutes. `deploy.sh` takes five to ten the first time —
it builds the backend image on the instance — and about two after that. The URL
is printed at the end, and is also `terraform -chdir=infra output url`.

## Deploying again

```bash
bash deploy/deploy.sh
```

Same script. It rebuilds, re-uploads and restarts. Migrations and the material
seed run automatically on container start and are idempotent, so there is no
separate step and no manual database work.

## Adding a domain

1. Point an `A` record at the `public_ip` output.
2. Set `public_host = "app.example.com"` in `terraform.tfvars`.
3. `terraform -chdir=infra apply` then `bash deploy/deploy.sh`.

Caddy obtains and renews a Let's Encrypt certificate on its own. Worth doing:
without HTTPS the browser will not treat the site as a secure context, which
restricts geolocation and some audio behaviour.

## Looking at it when something is wrong

```bash
aws ssm start-session --target "$(terraform -chdir=infra output -raw instance_id)" \
  --region "$(terraform -chdir=infra output -raw region)"

sudo docker compose -f /opt/bqs/docker-compose.yml logs --tail 200 -f
```

No open SSH port, no key pair, and every session is recorded in CloudTrail.

## Tearing it down

```bash
terraform -chdir=infra destroy
```

This deletes the database volume with the instance. Saved sites are not backed
up anywhere — export anything you want to keep first.

## What this deliberately does not do

**It does not scale horizontally.** One instance, one worker. The tile cache, the
voice cache and the Sarvam key-failover state all live in process memory, so a
second worker would keep its own copy and independently rediscover an exhausted
key. Scaling out means moving those to Redis first — the failover state is the
part that actually matters, since it is what keeps narration seamless when the
first key runs out.

**It has no automated backups.** Postgres runs in a container on a single EBS
volume. For anything beyond a demo, either enable EBS snapshots or move the
database to RDS.

**It is a single point of failure.** No health-checked replacement, no multi-AZ.
An instance failure is downtime until it is replaced.

All three are fine for a demo and none are fine for real users. The migration
path is the same in each case: move Postgres to RDS, put the API behind an ALB
in an autoscaling group, and add ElastiCache for the shared caches.

## Cost

Roughly **$18–22/month** in `ap-south-1`: the `t4g.small` is about $12, the
20 GB gp3 volume about $2, and the Elastic IP about $4 while attached. S3 and
SSM are effectively free at this size.

An Elastic IP is billed whether or not it is attached, so `destroy` when you are
finished rather than just stopping the instance.
