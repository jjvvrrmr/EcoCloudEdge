# Arquitectura EcoCloud Edge

> Plataforma cloud privada sobre clúster de 4 × Raspberry Pi 4B · k3s · ARM64  
> TFG — CFGS ASIR · Madrid 2025-2026

---

## 1. Topología del clúster

```
Red local: 192.168.1.0/24 · 100 Mbps
MetalLB Pool: 192.168.1.80–90

┌──────────────────────────────────────────────────────────────────────┐
│  node1 · 192.168.1.70 · Control Plane                               │
│  k3s API-Server · etcd · Controller · Scheduler                     │
│  Longhorn Manager · Traefik IngressController · MetalLB Speaker     │
├──────────────────┬──────────────────┬────────────────────────────────┤
│  node2 · .71     │  node3 · .72     │  node4 · .73                  │
│  k3s Agent       │  k3s Agent       │  k3s Agent                    │
│  Longhorn Rep.   │  Longhorn Rep.   │  Longhorn Rep.                │
│  Node Exporter   │  Node Exporter   │  Node Exporter                │
│  MariaDB 10.11   │  Nextcloud       │  Ollama (TinyLlama 1.1B-Q4)  │
│  LLDAP           │  AdGuard Home    │  Middleware Python             │
│                  │                  │  Prometheus · Grafana          │
└──────────────────┴──────────────────┴────────────────────────────────┘
```

**Recursos por nodo:** Raspberry Pi 4B · 4 GB RAM · ARM Cortex-A72 · almacenamiento local (microSD / USB)  
**Consumo total del clúster a plena carga: < 28 W** (frente a los > 400 W de un servidor 1U convencional)

---

## 2. Stack de servicios por capa

| Capa | Servicio | Versión | Función |
|------|----------|---------|---------|
| 1 — Orquestación | k3s | v1.34.6 | Control Plane + Agents (Kubernetes ligero, sin Docker) |
| 2 — Almacenamiento | Longhorn | v1.7.2 | StorageClass distribuida con 2 réplicas |
| 3 — Red / Exposición | Traefik | (bundled k3s) | Ingress Controller y proxy inverso TLS |
| 3 — Red / Exposición | MetalLB | v0.14.3 | LoadBalancer bare-metal para la red local |
| 4 — Identidad y DNS | LLDAP | latest | Directorio LDAP centralizado (panel en :17170) |
| 4 — Identidad y DNS | AdGuard Home | latest | DNS recursivo + bloqueo de rastreadores |
| 5 — Aplicaciones | Nextcloud | latest | Almacenamiento colaborativo y webhooks |
| 5 — Aplicaciones | MariaDB | 10.11 | Base de datos relacional para Nextcloud |
| 6 — IA On-Premise | Ollama | latest | Motor de inferencia LLM local |
| 6 — IA On-Premise | TinyLlama 1.1B-Q4 | — | Modelo cuantizado (~670 MB), resumen de documentos |
| 6 — IA On-Premise | Middleware Python | 3.10-alpine | Webhook bridge Nextcloud → Ollama |
| 7 — Monitorización | Prometheus | (helm) | Recolección de métricas por scrape |
| 7 — Monitorización | Grafana | (helm) | Dashboards en tiempo real |
| 7 — Monitorización | Node Exporter | (DaemonSet) | Métricas de hardware de cada nodo |

---

## 3. Flujo de datos principal

```
Usuario
  │
  ▼
AdGuard Home (DNS) ──► resuelve *.ecocloud.local → 192.168.1.81
  │
  ▼
MetalLB (192.168.1.80) ──► balancea tráfico hacia Traefik
  │
  ▼
Traefik (IngressController) ──► enruta por Host: header
  │
  ├──► nubes.ecocloud.local  → Nextcloud
  │         │
  │         └──► Webhook POST /prompt ──► Middleware Python (:5000)
  │                                             │
  │                                             └──► Ollama API (:11434)
  │                                                  (tinyllama · inferencia local)
  │
  └──► monitor.ecocloud.local → Grafana
            ▲
            └── Prometheus (scrape cada 15s) ◄── Node Exporter (todos los nodos)
```

### Flujo del Middleware Python (Nextcloud → Ollama)

El microservicio actúa como webhook receiver. Recibe un `POST` con `{ "prompt": "..." }`,
reenvía la petición a la API REST de Ollama y devuelve `{ "status": "success", "respuesta": "..." }`.

```
Nextcloud webhook
    │  POST /  { "prompt": "Resume este documento..." }
    ▼
Middleware Python (pod: middleware, puerto 5000)
    │  POST http://ollama-svc:11434/api/generate
    │  { "model": "tinyllama", "prompt": "...", "stream": false }
    ▼
Ollama (pod: ollama, puerto 11434)
    │  inferencia local · timeout 120s
    ▼
Middleware Python
    │  { "status": "success", "respuesta": "..." }
    ▼
Nextcloud (respuesta al webhook)
```

El código se inyecta vía **ConfigMap** para evitar construir una imagen personalizada en ARM64
con red de 100 Mbps. Imagen base: `python:3.10-alpine` (~50 MB vs ~900 MB de `python:3.10`).

---

## 4. Almacenamiento

```
┌─────────────────────────────────────────────────────────┐
│                  Longhorn StorageClass                  │
│               replicaCount: 2  (ver §5.1)               │
│                                                         │
│  node1-disk ◄──── replica ────► node2-disk             │
│  node2-disk ◄──── replica ────► node3-disk             │
│  node3-disk ◄──── replica ────► node4-disk             │
│                    (según scheduler Longhorn)           │
└─────────────────────────────────────────────────────────┘
         │
         ├── PVC: mariadb-data        (namespace: default)
         ├── PVC: nextcloud-data      (namespace: default)
         ├── PVC: ollama-models       (namespace: default)
         ├── PVC: adguard-data        (namespace: default)
         └── PVC: lldap-data          (namespace: default)
```

Todos los PersistentVolumeClaims usan `accessMode: ReadWriteOnce`. Esto impone la restricción
de estrategia de despliegue `Recreate` (ver 5.2).

---

## 5. Decisiones de diseño

### 5.1 · ¿Por qué 2 réplicas en Longhorn y no 3?

La red entre nodos es de **100 Mbps**. Con el valor por defecto de 3 réplicas, el tráfico de
sincronización de bloques saturaba el enlace compartido y degradaba la latencia de todos los
servicios. Se redujo a 2 réplicas mediante un ConfigMap aplicado **antes** del despliegue
de Longhorn (aplicarlo después no modifica volúmenes ya existentes).

**Trade-off asumido:** tolerancia a fallo de un solo nodo en lugar de dos. Aceptable dado que
el clúster es de uso doméstico y la disponibilidad no es crítica.

### 5.2 · ¿Por qué `strategy: Recreate` en todos los Deployments?

Todos los servicios montan volúmenes `ReadWriteOnce` (RWO). Con `RollingUpdate` (valor por
defecto de Kubernetes), el scheduler intenta levantar el pod nuevo **antes** de eliminar el
antiguo. El pod antiguo mantiene el bloqueo exclusivo del PVC → el pod nuevo queda en
`ContainerCreating` indefinidamente → **interbloqueo**.

La solución es forzar `strategy: Recreate`: primero termina el pod viejo (y libera el PVC) y
solo después arranca el nuevo.

### 5.3 · ¿Por qué TinyLlama 1.1B-Q4 y no un modelo mayor?

| Modelo | Tamaño en RAM | ¿Cabe en 4 GB? |
|--------|---------------|----------------|
| TinyLlama 1.1B-Q4 | ~670 MB | ✅ Con margen |
| Llama 3.2 3B-Q4 | ~2.0 GB | ⚠️ Justo |
| Mistral 7B-Q4 | ~4.1 GB | ❌ OOM Kill |
| Llama 3 8B-FP16 | ~16 GB | ❌ OOM Kill |

Tras OS + infraestructura de Kubernetes, quedan **~1.5 GB libres** por nodo. TinyLlama 1.1B-Q4
es el modelo más capaz que entra con margen suficiente para no provocar `OOM Kill` bajo carga.
Para el caso de uso concreto (resumen de documentos de texto plano), sus capacidades son
suficientes.

### 5.4 · ¿Por qué el Middleware usa un ConfigMap en lugar de una imagen Docker?

Construir y publicar una imagen personalizada ARM64 requeriría un registry accesible o
buildx en la Raspberry Pi (lento con red de 100 Mbps y CPU ARM de 4 núcleos). En cambio,
inyectar el script Python como ConfigMap montado en un volumen sobre `python:3.10-alpine`
(imagen pública de ~50 MB) reduce el tiempo de despliegue y elimina la dependencia de un
registry privado.

### 5.5 · ¿Por qué k3s y no k8s completo?

k3s elimina componentes que no aportan valor en hardware embebido (cloud-provider integrations,
in-tree volume plugins legacy) y empaqueta etcd, API Server, Controller Manager y Scheduler
en un único binario de ~100 MB. Esto reduce la huella de memoria del control plane de ~1.5 GB
(k8s convencional) a ~300 MB, crítico con solo 4 GB por nodo.

---

## 6. Red y exposición de servicios

```
MetalLB Pool: 192.168.1.80 – 192.168.1.90
```

| Servicio | Dominio interno | IP MetalLB | Puerto externo |
|----------|-----------------|------------|----------------|
| AdGuard Home (DNS) | — | 192.168.1.80 | UDP/TCP 53 |
| Nextcloud | nubes.ecocloud.local | 192.168.1.80 | 80 / 443 |
| Grafana | monitor.ecocloud.local | 192.168.1.80 | 80 / 443 |
| LLDAP (panel web) | — | ClusterIP | :17170 |
| Middleware Python | — | ClusterIP | :5000 (interno) |
| Ollama API | — | ClusterIP | :11434 (interno) |

> Los clientes de la red local deben apuntar su DNS a **192.168.1.80** (AdGuard Home)
> o añadir entradas en `/etc/hosts` / en el router para resolver `*.ecocloud.local`.

Nextcloud y Grafana comparten la IP `192.168.1.80` (Traefik) y Traefik los diferencia por
la cabecera `Host:` del request HTTP (virtual hosting).

---

## 7. Pipeline de despliegue (Ansible)

El despliegue se estructura en **6 hitos secuenciales** ejecutados con un único
playbook maestro (`ansible/site.yml`):

```
ansible-playbook -i inventory.ini site.yml
        │
        ├── HITO 1 — Base OS (todos los nodos)
        │     roles/base: cgroups, iSCSI initiator, desactivar swap
        │     roles/k3s_master: Control Plane
        │     roles/k3s_worker: unir nodos al clúster
        │
        ├── HITO 2 — Infraestructura de red y almacenamiento (master)
        │     roles/longhorn → ConfigMap réplicas + despliegue
        │     roles/traefik  → HelmChart CRD
        │     roles/metallb  → IPAddressPool + L2Advertisement
        │
        ├── HITO 3 — Identidad y DNS (master)
        │     roles/lldap    → Deployment + SealedSecret
        │     roles/lldap    → AdGuard Home (plantilla Jinja2)
        │
        ├── HITO 4 — Aplicaciones (master)
        │     roles/nextcloud → MariaDB + Nextcloud + PVCs
        │
        ├── HITO 5 — IA On-Premise (master)
        │     roles/ollama → Ollama + pull tinyllama + Middleware Python
        │
        └── HITO 6 — Monitorización (master)
              roles/monitoring → Prometheus + Grafana (HelmChart)
                                  Node Exporter (DaemonSet)
```

Los secretos se gestionan con **Ansible Vault** (`ansible/secrets.yml`) y,
para los objetos Kubernetes, con **Sealed Secrets** (ver `manifests/05-lldap/lldap-sealedsecret.yaml`).

---

## 8. CI/CD y calidad de código

El repositorio incluye un workflow de GitHub Actions (`.github/workflows/validate.yml`)
que se ejecuta en cada push y pull request:

| Check | Herramienta | Qué valida |
|-------|-------------|------------|
| YAML lint | yamllint | Formato y estilo de todos los `.yaml`/`.yml` |
| Kubernetes manifest validation | kubectl dry-run / kubeconform | Esquemas de API válidos |
| Ansible lint | ansible-lint | Buenas prácticas en playbooks y roles |
| Secret scan | detect-secrets / trufflehog | Que no se hayan commiteado credenciales |

---

## 9. Consideraciones de seguridad

- **Sin exposición a internet:** todos los servicios son internos a la red local `192.168.1.0/24`.
- **Autenticación centralizada:** LLDAP actúa como proveedor LDAP para los servicios que lo soporten.
- **Secretos en Vault / SealedSecrets:** las contraseñas nunca se almacenan en texto plano en el repo.
- **DNS con filtrado:** AdGuard Home bloquea dominios de rastreadores y malware a nivel de red.
- **IA completamente local:** las inferencias de TinyLlama no salen del clúster; los documentos procesados no se envían a servicios externos.

---

## 10. Estructura del repositorio

```
EcoCloudEdge/
├── ansible/
│   ├── inventory.ini.example   # Copia como inventory.ini y ajusta IPs
│   ├── secrets.yml.example     # Copia con tus contraseñas (cifrar con Vault)
│   ├── site.yml                # Playbook maestro (6 hitos)
│   └── roles/
│       ├── base/               # Hito 1: SO, cgroups, iSCSI, swap
│       ├── k3s_master/         # Hito 1: Control Plane
│       ├── k3s_worker/         # Hito 1: Workers
│       ├── longhorn/           # Hito 2: Almacenamiento distribuido
│       ├── traefik/            # Hito 2: Ingress Controller
│       ├── metallb/            # Hito 2: LoadBalancer bare-metal
│       ├── lldap/              # Hito 3: Identidad LDAP + AdGuard DNS
│       ├── nextcloud/          # Hito 4: MariaDB + Nextcloud
│       ├── ollama/             # Hito 5: IA + Middleware Python
│       └── monitoring/         # Hito 6: Prometheus + Grafana
├── manifests/                  # YAMLs puros para aplicación manual
│   ├── 01-namespaces/
│   ├── 02-longhorn/
│   ├── 03-traefik/
│   ├── 04-metallb/
│   ├── 05-lldap/
│   ├── 06-adguard/
│   ├── 07-mariadb/
│   ├── 08-nextcloud/
│   ├── 09-ollama/
│   └── 10-monitoring/
├── middleware/
│   ├── main.py                 # Webhook Python (Nextcloud → Ollama)
│   └── Dockerfile
├── docs/
│   ├── architecture.md         # Este documento
│   └── troubleshooting.md      # Incidencias reales con causa raíz y solución
├── .github/workflows/
│   └── validate.yml            # CI: lint + validación + secret scan
└── README.md
```
