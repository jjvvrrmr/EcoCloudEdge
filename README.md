# EcoCloud Edge

> Plataforma cloud privada y sostenible sobre clúster de Raspberry Pi 4B con k3s  
> TFG — CFGS Administración de Sistemas Informáticos en Red (ASIR) · Madrid 2025-2026

[![Validate](https://github.com/jjvvrrmr/ecocloud-edge/actions/workflows/validate.yml/badge.svg)](https://github.com/jjvvrrmr/ecocloud-edge/actions/workflows/validate.yml)

---

## ¿Qué es esto?

Un clúster de **4 Raspberry Pi 4B** (4 GB RAM cada una) que ejecuta una nube privada completa:
almacenamiento colaborativo, autenticación centralizada, DNS con bloqueo de rastreadores,
inferencia de IA local y monitorización en tiempo real. Todo con software libre, sin salida a
internet para los datos y por menos de 200 € de hardware.

**Consumo total del clúster a plena carga: < 28 W** (frente a los >400 W de un servidor 1U convencional).

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Orquestación | k3s v1.34.6 (Kubernetes ligero) |
| Almacenamiento | Longhorn v1.7.2 |
| Ingress / Proxy | Traefik |
| LoadBalancer | MetalLB v0.14.3 |
| Identidad | LLDAP (directorio LDAP) |
| DNS + Seguridad | AdGuard Home |
| Almacenamiento colaborativo | Nextcloud + MariaDB 10.11 |
| IA On-Premise | Ollama + TinyLlama 1.1B-Q4 |
| Middleware | Python 3.10 (Alpine) |
| Monitorización | Prometheus + Grafana |

## Estructura del repositorio

```
ecocloud-edge/
├── ansible/
│   ├── inventory.ini.example   # Copia como inventory.ini y ajusta IPs
│   ├── site.yml                # Playbook maestro (6 hitos)
│   └── roles/
│       ├── base/               # Hito 1: SO, cgroups, iSCSI
│       ├── k3s_master/         # Hito 1: Control Plane
│       ├── k3s_worker/         # Hito 1: Workers
│       ├── longhorn/           # Hito 2: Almacenamiento distribuido
│       ├── traefik/            # Hito 2: Ingress Controller
│       ├── metallb/            # Hito 2: LoadBalancer bare-metal
│       ├── lldap/              # Hito 3: Identidad + AdGuard DNS
│       ├── nextcloud/          # Hito 4: MariaDB + Nextcloud
│       ├── ollama/             # Hito 5: IA + Middleware Python
│       └── monitoring/         # Hito 6: Prometheus + Grafana
├── manifests/                  # YAMLs puros (sin Ansible)
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
│   └── main.py                 # Código Python del webhook Nextcloud→Ollama
├── docs/
│   ├── architecture.md         # Diagrama de topología y decisiones de diseño
│   └── troubleshooting.md      # 8 incidencias reales con causa raíz y solución
├── .github/
│   └── workflows/
│       └── validate.yml        # CI: YAML lint + k8s validate + secret scan
├── .env.example                # Variables requeridas (sin valores reales)
├── .gitignore
└── README.md
```

## Arranque rápido

### Opción A — Ansible (recomendado, automatiza todo)

```bash
# 1. Clona el repositorio
git clone https://github.com/TU_USUARIO/ecocloud-edge.git
cd ecocloud-edge

# 2. Configura el inventario
cp ansible/inventory.ini.example ansible/inventory.ini
# Edita ansible/inventory.ini con las IPs y usuario SSH de tus Raspberry Pi

# 3. Configura las variables secretas
cp .env.example .env
# Edita .env con tus contraseñas reales

# 4. Ejecutar el despliegue completo
ansible-playbook -i ansible/inventory.ini ansible/site.yml

# O por hito individual:
ansible-playbook -i ansible/inventory.ini ansible/site.yml --tags hito1
ansible-playbook -i ansible/inventory.ini ansible/site.yml --tags hito2
# ...
```

### Opción B — Manifiestos directos (sin Ansible)

```bash
# En node1, aplicar en orden:
sudo k3s kubectl apply -f manifests/01-namespaces/
sudo k3s kubectl apply -f manifests/02-longhorn/longhorn-configmap.yaml
sudo k3s kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.7.2/deploy/longhorn.yaml
# ... (ver docs/architecture.md para el orden completo)
```

## Verificación de cada hito

```bash
# Hito 1 — Los 4 nodos en Ready
sudo k3s kubectl get nodes

# Hito 2 — Longhorn, Traefik y MetalLB operativos
sudo k3s kubectl get pods -n longhorn-system
sudo k3s kubectl get pods -n kube-system | grep traefik
sudo k3s kubectl get pods -n metallb-system

# Hito 3 — LLDAP Running (0 reinicios), AdGuard con IP externa
sudo k3s kubectl get pods -l "app in (lldap,adguard)"
sudo k3s kubectl get svc adguard-svc

# Hito 4 — Acceso a Nextcloud
curl -I -H "Host: nubes.ecocloud.local" http://192.168.1.81

# Hito 5 — IA respondiendo
sudo k3s kubectl exec deploy/ollama -- ollama run tinyllama "¿De qué color es el cielo?"

# Hito 6 — Grafana accesible
curl -I -H "Host: monitor.ecocloud.local" http://192.168.1.81
```

## Problemas conocidos

Ver [`docs/troubleshooting.md`](docs/troubleshooting.md) para las 8 incidencias documentadas
durante el despliegue real, con causa raíz y solución verificada.

## Seguridad

- **No hay secretos en este repositorio.** Todas las contraseñas van en `.env` (ignorado por Git).
- Los manifiestos en `manifests/` usan variables `${VAR}` para sustituir con `envsubst`.
- Los templates Ansible usan variables Jinja2 `{{ var }}` resueltas en tiempo de ejecución.
- El CI tiene un job `secret-scan` que detecta contraseñas hardcodeadas antes de cualquier merge.

## Autores

- Alejandro Goyanes Matallanos  
- Javier Maldonado Ramírez  
- Iván Honrubia Llorente  

CFGS ASIR · Madrid · Curso 2025–2026
