# Arquitectura EcoCloud Edge

> Plataforma cloud privada sobre clúster de 4 × Raspberry Pi 4B · k3s · ARM64
> TFG — CFGS ASIR · Madrid 2025-2026

---

## 1. Topología del clúster

```
Red local: 192.168.1.0/24 · 100 Mbps
MetalLB Pool: 192.168.1.80–90

┌──────────────────────────────────────────────────────────────────────┐
│  node1 · 192.168.1.70 · Control Plane                                │
│  k3s API-Server · etcd · Controller · Scheduler                      │
│  Longhorn Manager · Traefik IngressController · MetalLB Speaker      │
├──────────────────┬──────────────────┬────────────────────────────────┤
│  node2 · .71     │  node3 · .72     │  node4 · .73                   │
│  k3s Agent       │  k3s Agent       │  k3s Agent                     │
│  Longhorn Rep.   │  Longhorn Rep.   │  Longhorn Rep.                 │
│  Node Exporter   │  Node Exporter   │  Node Exporter                 │
│  MariaDB 10.11   │  Nextcloud 30    │  Ollama 0.5.1                  │
│  LLDAP v0.6.1    │  AdGuard v0.107  │  TinyLlama 1.1B-Q4             │
│                  │                  │  Middleware Python 3.10        │
│                  │                  │  Prometheus · Grafana          │
└──────────────────┴──────────────────┴────────────────────────────────┘
```

> La distribución de pods entre nodos la decide el scheduler de k3s en función
> de la carga en el momento del despliegue. El diagrama muestra la distribución
> observada en el entorno real del TFG.

**Recursos por nodo:** Raspberry Pi 4B · 4 GB RAM · ARM Cortex-A72 · almacenamiento local (microSD / USB)
**Consumo total del clúster a plena carga: < 28 W** (frente a los > 400 W de un servidor 1U convencional)

---

## 2. Stack de servicios por capa

| Capa | Servicio | Versión fijada | Función |
|------|----------|----------------|---------|
| 1 — Orquestación | k3s | latest estable (script oficial) | Control Plane + Agents (Kubernetes ligero, sin Docker) |
| 2 — Almacenamiento | Longhorn | v1.7.2 | StorageClass distribuida con 2 réplicas |
| 3 — Red / Exposición | Traefik | chart sin versión fijada | Ingress Controller y proxy inverso |
| 3 — Red / Exposición | MetalLB | v0.14.3 | LoadBalancer bare-metal para la red local |
| 4 — Identidad y DNS | LLDAP | v0.6.1 | Directorio LDAP centralizado (panel en :17170) |
| 4 — Identidad y DNS | AdGuard Home | v0.107.54 | DNS recursivo + bloqueo de rastreadores |
| 5 — Aplicaciones | Nextcloud | 30.0.5 (linuxserver) | Almacenamiento colaborativo y webhooks |
| 5 — Aplicaciones | MariaDB | 10.11 | Base de datos relacional para Nextcloud |
| 6 — IA On-Premise | Ollama | 0.5.1 | Motor de inferencia LLM local |
| 6 — IA On-Premise | TinyLlama 1.1B-Q4 | — | Modelo cuantizado (~670 MB), resumen de documentos |
| 6 — IA On-Premise | Middleware Python | 3.10-alpine | Webhook bridge Nextcloud → Ollama |
| 7 — Monitorización | kube-prometheus-stack | chart sin versión fijada | Prometheus + Grafana + Node Exporter |
| 7 — Monitorización | Node Exporter | (DaemonSet en los 4 nodos) | Métricas de hardware de cada nodo |

---

## 3. Flujo de datos principal

```
Usuario
  │
  ▼
AdGuard Home (DNS) ──► resuelve *.ecocloud.local → 192.168.1.80
  │
  ▼
MetalLB (192.168.1.80) ──► asigna IP al Service de Traefik
  │
  ▼
Traefik (IngressController) ──► enruta por cabecera Host:
  │
  ├──► nubes.ecocloud.local  → Nextcloud
  │         │
  │         └──► Webhook POST /  { "prompt": "..." }
  │                    │
  │                    ▼
  │              Middleware Python (:5000)
  │                    │
  │                    └──► POST http://ollama-svc:11434/api/generate
  │                              { "model": "tinyllama", "stream": false }
  │                                        │
  │                                        ▼
  │                                 Ollama (inferencia local · timeout 120s)
  │                                        │
  │                              { "status": "success", "respuesta": "..." }
  │
  └──► monitor.ecocloud.local → Grafana
            ▲
            └── Prometheus (scrape cada 15s) ◄── Node Exporter (DaemonSet)
```

### Flujo del Middleware Python (Nextcloud → Ollama)

El microservicio actúa como webhook receiver. Acepta `GET /health` para los probes
de Kubernetes y `POST /` con `{ "prompt": "..." }` para la inferencia. Devuelve
`{ "status": "success", "respuesta": "..." }` o un error JSON con el código HTTP
correspondiente (400 para JSON malformado, 500 para fallos de Ollama).

El código se inyecta vía **ConfigMap** (`middleware-script`) montado en `/app` sobre
`python:3.10-alpine` (~50 MB vs ~900 MB de `python:3.10`), evitando construir una
imagen personalizada ARM64 con la red de 100 Mbps del clúster.

---

## 4. Almacenamiento

```
┌─────────────────────────────────────────────────────────┐
│                  Longhorn StorageClass                  │
│               replicaCount: 2  (ver §5.1)               │
│                                                         │
│Volumen ◄──── réplica principal ────► réplica secundaria │
│           (scheduler Longhorn elige los nodos)          │
└─────────────────────────────────────────────────────────┘
```

Todos los PersistentVolumeClaims usan `accessMode: ReadWriteOnce` (RWO). Esto impone
`strategy: Recreate` en todos los Deployments (ver §5.2).

| PVC | Tamaño | Servicio | Namespace |
|-----|--------|----------|-----------|
| lldap-data | 1 Gi | LLDAP (SQLite) | default |
| adguard-work | 2 Gi | AdGuard Home (logs, caché) | default |
| adguard-conf | 1 Gi | AdGuard Home (configuración) | default |
| mariadb-data | 5 Gi | MariaDB | default |
| nextcloud-config | 2 Gi | Nextcloud (nginx/php/app) | default |
| nextcloud-data | 5 Gi | Nextcloud (archivos de usuario) | default |
| ollama-data | 5 Gi | Ollama (modelos descargados) | default |

> Nextcloud usa **dos PVCs separados** (`nextcloud-config` y `nextcloud-data`) para
> evitar que la configuración de la aplicación y los archivos de usuario compartan
> el mismo árbol de directorios, lo que causaría corrupción al reiniciar el pod.

---

## 5. Decisiones de diseño

### 5.1 · ¿Por qué 2 réplicas en Longhorn y no 3?

La red entre nodos es de **100 Mbps**. Con el valor por defecto de 3 réplicas, el
tráfico de sincronización de bloques saturaba el enlace compartido y degradaba la
latencia de todos los servicios. Se redujo a 2 réplicas mediante un ConfigMap
aplicado **antes** del despliegue de Longhorn; aplicarlo después no modifica
volúmenes ya existentes.

**Trade-off asumido:** tolerancia a fallo de un solo nodo en lugar de dos.
Aceptable dado que el clúster es de uso doméstico y la disponibilidad no es crítica.

### 5.2 · ¿Por qué `strategy: Recreate` en todos los Deployments?

Todos los servicios montan volúmenes `ReadWriteOnce` (RWO). Con `RollingUpdate`
(valor por defecto de Kubernetes), el scheduler intenta levantar el pod nuevo
**antes** de eliminar el antiguo. El pod antiguo mantiene el bloqueo exclusivo del
PVC → el pod nuevo queda en `ContainerCreating` indefinidamente → **interbloqueo**.

`strategy: Recreate` garantiza que el pod viejo libera el PVC antes de que el
nuevo intente montarlo.

### 5.3 · ¿Por qué TinyLlama 1.1B-Q4 y no un modelo mayor?

| Modelo | Tamaño en RAM | ¿Cabe en 4 GB? |
|--------|---------------|----------------|
| TinyLlama 1.1B-Q4 | ~670 MB | ✅ Con margen |
| Llama 3.2 3B-Q4 | ~2.0 GB | ⚠️ Justo |
| Mistral 7B-Q4 | ~4.1 GB | ❌ OOM Kill |
| Llama 3 8B-FP16 | ~16 GB | ❌ OOM Kill |

Tras OS + infraestructura de Kubernetes, quedan **~1.5 GB libres** por nodo.
TinyLlama 1.1B-Q4 es el modelo más capaz que entra con margen suficiente para
no provocar `OOM Kill` bajo carga. Para el caso de uso concreto (resumen de
documentos de texto plano), sus capacidades son suficientes.

El límite de RAM del pod de Ollama se fija explícitamente en `2Gi` para que el
OOM Killer actúe sobre el pod antes de sobre el nodo completo.

### 5.4 · ¿Por qué el Middleware usa un ConfigMap en lugar de una imagen Docker?

Construir y publicar una imagen personalizada ARM64 requeriría un registry
accesible o `buildx` en la Raspberry Pi (lento con red de 100 Mbps y CPU ARM
de 4 núcleos). Inyectar el script Python como ConfigMap montado en un volumen
sobre `python:3.10-alpine` (~50 MB) reduce el tiempo de despliegue y elimina la
dependencia de un registry privado.

El `Dockerfile` incluido en `middleware/` sirve como referencia para desarrollo
local o si en el futuro se quiere publicar la imagen en un registry.

### 5.5 · ¿Por qué k3s y no k8s completo?

k3s empaqueta etcd, API Server, Controller Manager y Scheduler en un único
binario de ~100 MB, eliminando componentes innecesarios en hardware embebido
(cloud-provider integrations, in-tree volume plugins legacy). Reduce la huella
de memoria del control plane de ~1.5 GB (k8s convencional) a ~300 MB, crítico
con solo 4 GB por nodo.

k3s se instala con `--disable traefik --disable servicelb --disable local-storage`
para desplegar versiones personalizadas de Traefik (vía HelmChart CRD) y MetalLB
(como LoadBalancer bare-metal) en su lugar.

---

## 6. Red y exposición de servicios

```
MetalLB Pool: 192.168.1.80 – 192.168.1.90
```

| Servicio | Dominio | IP / Tipo | Puerto externo |
|----------|---------|-----------|----------------|
| AdGuard Home (DNS) | — | LoadBalancer · 192.168.1.80 | UDP/TCP 53, TCP 3000 (panel), TCP 80 |
| Nextcloud | nubes.ecocloud.local | Ingress → Traefik · 192.168.1.80 | TCP 80 |
| Grafana | monitor.ecocloud.local | Ingress → Traefik · 192.168.1.80 | TCP 80 |
| LLDAP (panel web) | — | ClusterIP | :17170 (port-forward) |
| LLDAP (LDAP) | — | ClusterIP | :3890 (interno) |
| Middleware Python | — | ClusterIP | :5000 (interno) |
| Ollama API | — | ClusterIP | :11434 (interno) |
| MariaDB | — | ClusterIP | :3306 (interno) |

> Los clientes de la red local deben apuntar su DNS a **192.168.1.80** (AdGuard Home)
> o añadir entradas en `/etc/hosts` para resolver `*.ecocloud.local`.
>
> Nextcloud y Grafana comparten la IP `192.168.1.80` (Traefik) y se diferencian
> por la cabecera `Host:` del request HTTP (virtual hosting).

---

## 7. Pipeline de despliegue (Ansible)

El despliegue se estructura en **6 hitos secuenciales** ejecutados con un único
playbook maestro (`ansible/site.yml`):

```
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e @ansible/secrets.yml
        │
        ├── HITO 1 — Base OS (todos los nodos)
        │     roles/base:        cgroups, iSCSI initiator, desactivar swap
        │                        → handler: reinicio automático si se modifica cmdline.txt
        │     roles/k3s_master:  Control Plane (--disable traefik/servicelb/local-storage)
        │     roles/k3s_worker:  unir nodos al clúster vía token del master
        │
        ├── HITO 2 — Infraestructura de red y almacenamiento (master)
        │     roles/longhorn  → ConfigMap réplicas (2) + despliegue v1.7.2
        │     roles/traefik   → HelmChart CRD (kube-system)
        │     roles/metallb   → MetalLB v0.14.3 + IPAddressPool + L2Advertisement
        │
        ├── HITO 3 — Identidad y DNS (master)
        │     roles/lldap     → LLDAP v0.6.1 (Deployment + PVC + Service)
        │     roles/lldap     → AdGuard Home v0.107.54 (LoadBalancer vía MetalLB)
        │
        ├── HITO 4 — Aplicaciones (master)
        │     roles/nextcloud → MariaDB 10.11 + Nextcloud 30.0.5 + PVCs + Ingress
        │
        ├── HITO 5 — IA On-Premise (master)
        │     roles/ollama    → Ollama 0.5.1 + pull tinyllama (~650 MB)
        │                    → Middleware Python 3.10-alpine (ConfigMap + Deployment)
        │
        └── HITO 6 — Monitorización (master)
              roles/monitoring → kube-prometheus-stack (HelmChart)
                                  Prometheus (retención 2d, límite 500 Mi RAM)
                                  Grafana (Ingress → monitor.ecocloud.local)
                                  Node Exporter (DaemonSet en los 4 nodos)
```

### Convenciones de los roles Ansible

Todos los roles siguen las mismas convenciones para pasar ansible-lint (perfil `basic`):

- Módulos con **FQCN** (`ansible.builtin.*`) en todas las tareas.
- Variables `register` con **prefijo del rol** (`longhorn_ns_create`, `ollama_model_pull`, etc.).
- `changed_when: false` en todos los comandos de consulta; `changed_when` basado en
  resultado en comandos que crean recursos.
- `mode: '0644'` en todas las tareas `copy` y `template`.
- `set -o pipefail` en todos los bloques `shell` con pipes.
- El **reboot** tras modificar `cmdline.txt` se gestiona como handler en
  `roles/base/handlers/main.yml`, no como tarea condicional.

Los secretos se pasan en tiempo de ejecución con `-e @ansible/secrets.yml`.
Nunca se almacenan en el repositorio.

---

## 8. CI/CD y calidad de código

El repositorio incluye un workflow de GitHub Actions (`.github/workflows/validate.yml`)
que se ejecuta en cada push y pull request sobre `main`:

| Job | Herramienta | Qué valida |
|-----|-------------|------------|
| YAML Lint | yamllint | Formato y estilo de todos los `.yaml`/`.yml` (excluye SealedSecrets y templates `.j2`) |
| Kubernetes Manifest Validation | kubeconform | Esquemas de API Kubernetes válidos contra el catálogo oficial de CRDs |
| Ansible Lint | ansible-lint | Buenas prácticas en playbooks y roles (perfil `basic`: FQCN, var-naming, changed-when, etc.) |
| Python Lint | flake8 | Estilo PEP 8 del middleware (max-line-length=100) |
| Secret Scan | detect-secrets | Detección de credenciales hardcodeadas antes de cualquier merge |
| Pipeline Summary | — | Resumen agregado del resultado de todos los jobs |

Todos los jobs deben pasar para que un PR sea mergeable.

---

## 9. Consideraciones de seguridad

- **Sin exposición a internet:** todos los servicios son internos a `192.168.1.0/24`.
- **Autenticación centralizada:** LLDAP v0.6.1 actúa como proveedor LDAP. Nextcloud
  se integra vía plugin "LDAP user and group backend" apuntando a `lldap-svc:3890`.
- **Secretos fuera del repo:** las contraseñas van en `ansible/secrets.yml`
  (en `.gitignore`). Los manifests usan variables `${VAR}` para `envsubst` o
  templates Jinja2 resueltos en tiempo de ejecución.
- **DNS con filtrado:** AdGuard Home bloquea dominios de rastreadores y malware a
  nivel de red para todos los dispositivos que lo usen como DNS primario.
- **IA completamente local:** las inferencias de TinyLlama no salen del clúster;
  los documentos procesados nunca se envían a servicios externos.
- **Ollama no expuesto externamente:** la API de Ollama (`:11434`) es ClusterIP,
  accesible solo desde dentro del clúster (el Middleware actúa de proxy).

---

## 10. Estructura del repositorio

```
EcoCloudEdge/
├── ansible/
│   ├── inventory.ini.example        # Copia como inventory.ini y ajusta IPs
│   ├── secrets.yml.example          # Copia con tus contraseñas (en .gitignore)
│   ├── site.yml                     # Playbook maestro (6 hitos)
│   └── roles/
│       ├── base/
│       │   ├── tasks/main.yml       # Hito 1: SO, cgroups, iSCSI, swap
│       │   └── handlers/main.yml    # Handler: reboot si se modifica cmdline.txt
│       ├── k3s_master/tasks/        # Hito 1: Control Plane
│       ├── k3s_worker/tasks/        # Hito 1: Workers
│       ├── longhorn/tasks/          # Hito 2: Almacenamiento distribuido
│       ├── traefik/tasks/           # Hito 2: Ingress Controller
│       ├── metallb/                 # Hito 2: LoadBalancer bare-metal
│       │   ├── tasks/main.yml
│       │   └── templates/metallb-pool.yaml.j2
│       ├── lldap/                   # Hito 3: Identidad LDAP + AdGuard DNS
│       │   ├── tasks/main.yml
│       │   └── templates/{lldap,adguard}.yaml.j2
│       ├── nextcloud/               # Hito 4: MariaDB + Nextcloud
│       │   ├── tasks/main.yml
│       │   └── templates/{mariadb,nextcloud}.yaml.j2
│       ├── ollama/                  # Hito 5: IA + Middleware Python
│       │   ├── tasks/main.yml
│       │   └── templates/{ollama,middleware}.yaml.j2
│       └── monitoring/              # Hito 6: Prometheus + Grafana
│           ├── tasks/main.yml
│           └── templates/monitoring-helmchart.yaml.j2
├── manifests/                       # YAMLs para despliegue manual (Opción B)
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
│   ├── main.py                      # Webhook Python (Nextcloud → Ollama)
│   └── Dockerfile                   # Para desarrollo local / imagen futura
├── docs/
│   ├── architecture.md              # Este documento
│   └── troubleshooting.md           # Incidencias reales con causa raíz y solución
├── .github/workflows/
│   └── validate.yml                 # CI: yamllint + kubeconform + ansible-lint + flake8 + secret-scan
├── .yamllint.yml                    # Configuración de yamllint
├── .gitignore
└── README.md
```
