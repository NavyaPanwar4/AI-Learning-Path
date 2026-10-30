# Database migrations

Production deployments should set `AUTO_CREATE_SCHEMA=false` and run:

```powershell
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```

Review generated migrations before applying them. The development default keeps
`AUTO_CREATE_SCHEMA=true` for a fresh local checkout.
