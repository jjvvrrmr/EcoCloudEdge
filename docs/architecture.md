# Arquitectura EcoCloud Edge

## Topología del clúster

```
Red local: 192.168.1.0/24 · 100 Mbps
MetalLB Pool: 192.168.1.80–90

┌─────────────────────────────────────────────────────────────────┐
│  node1 · 192.168.1.70 · Control Plane                          │
│  k3s API-Server · etcd · Controller · Scheduler                │
│  Longhorn Manager · Traefik · MetalLB Speaker                  │
├────────────────┬────────────────┬───────────────────────────────┤
│ node2 · .71   │ node3 · .72   │ node4 · .73                   │
│ k3s Agent     │ k3s Agent     │ k3s Agent                     │
│ Longhorn Rep. │ Longhorn Rep. │ Longhorn Rep.                 │
│ Node Exporter │ Node Exporter │ Node Exporter                 │
│ MariaDB       │ Nextcloud     │ Ollama (TinyLlama)            │
│ LLDAP         │ AdGuard Home  │ Middleware Python             │
│               │               │ Prometheus · Grafana          │
└───────────────┴───────────────┴───────────────────────────────┘
```

## Stack de servicios por capa

| Capa | Servicio | Función |
|------|----------|---------|
| 1 — Orquestación | k3s v1.34.6 | Control Plane + Agents |
| 2 — Almacenamiento | Longhorn v1.7.2 | StorageClass distribuida (2 réplicas) |
| 3 — Red/Exposición | Traefik | Ingress Controller / Proxy Inverso |
| 3 — Red/Exposición | MetalLB v0.14.3 | LoadBalancer bare-metal |
| 4 — Identidad y DNS | LLDAP | Directorio LDAP centralizado |
| 4 — Identidad y DNS | AdGuard Home | DNS + bloqueo de rastreadores |
| 5 — Aplicaciones | Nextcloud | Almacenamiento colaborativo |
| 5 — Aplicaciones | MariaDB 10.11 | Base de datos relacional |
| 6 — IA On-Premise | Ollama | Motor de inferencia LLM |
| 6 — IA On-Premise | TinyLlama 1.1B-Q4 | Modelo cuantizado (~670 MB) |
| 6 — IA On-Premise | Middleware Python | Puente Nextcloud → Ollama |
| 7 — Monitorización | Prometheus | Recolección de métricas |
| 7 — Monitorización | Grafana | Dashboards en tiempo real |
| 7 — Monitorización | Node Exporter | Métricas de nodo (DaemonSet) |

## Decisiones de diseño relevantes

### ¿Por qué 2 réplicas en Longhorn?
La red entre nodos es de 100 Mbps. Con 3 réplicas (defecto), el tráfico de
sincronización saturaba el enlace y degradaba todos los servicios. Limitado
a 2 mediante ConfigMap aplicado **antes** del despliegue de Longhorn.

### ¿Por qué `strategy: Recreate` en todos los Deployments?
Todos los servicios usan volúmenes `ReadWriteOnce`. Con `RollingUpdate`
(defecto), Kubernetes intenta levantar el pod nuevo antes de destruir el
antiguo, que mantiene el bloqueo exclusivo del volumen → interbloqueo.

### ¿Por qué TinyLlama y no un modelo mayor?
Cada nodo tiene 4 GB de RAM. Tras OS + infraestructura, quedan ~1.5 GB
libres. Un modelo 7B en FP16 requiere ~14 GB → OOM Kill inmediato.
TinyLlama 1.1B-Q4 cabe en ~670 MB con capacidades razonables para
resumen de documentos.

## Dominios internos

| Servicio | Dominio | IP (MetalLB) |
|----------|---------|--------------|
| Nextcloud | nubes.ecocloud.local | 192.168.1.81 |
| Grafana | monitor.ecocloud.local | 192.168.1.81 |
| AdGuard Home | — | 192.168.1.80 |
| LLDAP (panel) | — | ClusterIP:17170 |

> Los clientes externos necesitan entrada en `/etc/hosts` o en el router
> apuntando el dominio `ecocloud.local` a AdGuard Home (192.168.1.80).
